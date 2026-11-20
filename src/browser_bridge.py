import asyncio
import ctypes
import json
import os
import re
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
import websockets

from src.ai_sites import AI_SITES, DEFAULT_SITE_URL
from src.chat_text import clean_chat_reply

DEFAULT_CDP_PORT = 9222
_BROWSER_LOCK = asyncio.Lock()
_PROFILE_DIR = Path(__file__).resolve().parent.parent / ".browser_profile"


@dataclass(frozen=True)
class BrowserInfo:
    """CDP (--remote-debugging-port) destekleyen, Chromium tabanlı bir tarayıcının tanımı."""

    key: str
    label: str
    progid_hint: str  # Windows UserChoice ProgId içinde aranan metin (küçük harf)
    exe_paths: tuple
    profile_dir: str  # kullanıcının gerçek oturumlarının bulunduğu 'User Data' dizini


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _supported_browsers() -> List[BrowserInfo]:
    local, roaming = _env("LOCALAPPDATA"), _env("APPDATA")
    pf, pf86 = r"C:\Program Files", r"C:\Program Files (x86)"
    return [
        BrowserInfo(
            "chrome", "Google Chrome", "chromehtml",
            (pf + r"\Google\Chrome\Application\chrome.exe", pf86 + r"\Google\Chrome\Application\chrome.exe",
             local + r"\Google\Chrome\Application\chrome.exe"),
            local + r"\Google\Chrome\User Data",
        ),
        BrowserInfo(
            "edge", "Microsoft Edge", "msedgehtm",
            (pf86 + r"\Microsoft\Edge\Application\msedge.exe", pf + r"\Microsoft\Edge\Application\msedge.exe",
             local + r"\Microsoft\Edge\Application\msedge.exe"),
            local + r"\Microsoft\Edge\User Data",
        ),
        BrowserInfo(
            "opera_gx", "Opera GX", "operagx",
            (local + r"\Programs\Opera GX\opera.exe", pf + r"\Opera GX\opera.exe"),
            roaming + r"\Opera Software\Opera GX Stable",
        ),
        BrowserInfo(
            "opera", "Opera", "opera",
            (local + r"\Programs\Opera\opera.exe", pf + r"\Opera\opera.exe"),
            roaming + r"\Opera Software\Opera Stable",
        ),
        BrowserInfo(
            "brave", "Brave", "brave",
            (pf + r"\BraveSoftware\Brave-Browser\Application\brave.exe",
             local + r"\BraveSoftware\Brave-Browser\Application\brave.exe"),
            local + r"\BraveSoftware\Brave-Browser\User Data",
        ),
        BrowserInfo(
            "vivaldi", "Vivaldi", "vivaldi",
            (local + r"\Vivaldi\Application\vivaldi.exe", pf + r"\Vivaldi\Application\vivaldi.exe"),
            local + r"\Vivaldi\User Data",
        ),
    ]


def _first_existing(paths: tuple) -> Optional[str]:
    for path_str in paths:
        if path_str and Path(path_str).is_file():
            return path_str
    return None


def pick_browser(progid: str, browsers: Optional[List[BrowserInfo]] = None) -> Optional[tuple]:
    """Varsayılan tarayıcının ProgId'sine göre (BrowserInfo, exe) çifti döndürür; yoksa kurulu ilk desteklenen tarayıcı.

    Sıralama önemlidir: 'operagx' ProgId'si 'opera' ipucunu da içerdiği için GX önce denenir.
    """
    browsers = browsers if browsers is not None else _supported_browsers()
    progid = (progid or "").lower()
    for b in browsers:
        if progid and b.progid_hint in progid:
            exe = _first_existing(b.exe_paths)
            if exe:
                return b, exe
    for b in browsers:  # varsayılan desteklenmiyorsa (örn. Firefox) kurulu olan ilk Chromium tarayıcı
        exe = _first_existing(b.exe_paths)
        if exe:
            return b, exe
    return None


def _default_browser_progid() -> str:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        ) as key:
            return str(winreg.QueryValueEx(key, "ProgId")[0])
    except Exception:
        return ""


def describe_default_browser() -> str:
    """Arayüzde gösterilecek, köprünün kullanacağı tarayıcının adı."""
    picked = pick_browser(_default_browser_progid())
    return picked[0].label if picked else "bulunamadı (Chrome/Edge/Opera/Brave kurun)"


def _find_default_browser_executable() -> Optional[str]:
    """Windows'ta varsayılan HTTPS tarayıcısını bulur (Chrome, Edge, Opera, Opera GX, Brave, Vivaldi)."""
    picked = pick_browser(_default_browser_progid())
    return picked[1] if picked else None


def _browser_for_exe(exe_path: str) -> Optional[BrowserInfo]:
    """Yürütülebilir dosya yoluna karşılık gelen tarayıcı tanımı (Opera / Opera GX ayrımı dahil)."""
    low = exe_path.lower()
    name = Path(low).name
    for b in _supported_browsers():
        if name not in {Path(e).name.lower() for e in b.exe_paths}:
            continue
        if b.key == "opera" and "opera gx" in low:
            continue
        if b.key == "opera_gx" and "opera gx" not in low:
            continue
        return b
    return None


def _default_profile_dir(exe_path: str) -> Optional[Path]:
    """Tarayıcı yürütülebilir dosyasına göre varsayılan 'User Data' dizinini döndürür."""
    b = _browser_for_exe(exe_path)
    if b is None:
        return None
    cand = Path(b.profile_dir)
    return cand if cand.is_dir() else None


# Oturum taşımak için gereken en az dosya/klasör (geçmiş, parola veritabanı, form verisi KOPYALANMAZ).
_SEED_ROOT_FILES = ("Local State",)
_SEED_PROFILE_ITEMS = (
    "Network", "Local Storage", "Session Storage", "IndexedDB", "Preferences", "Secure Preferences",
    "Cookies", "Extension Cookies",
)


def profile_dir_for(browser_key: Optional[str]) -> Path:
    """Her tarayıcı için ayrı köprü profili.

    Oturum çerezleri içerdiği için profiller OneDrive/Dropbox gibi eşitlenen klasörlerin DIŞINDA,
    %LOCALAPPDATA%\LLMGuardAuditor\profiles altında tutulur (yoksa proje klasörüne düşülür).
    """
    local = os.environ.get("LOCALAPPDATA")
    key = browser_key or "chrome"
    if local:
        return Path(local) / "LLMGuardAuditor" / "profiles" / key
    return Path(__file__).resolve().parent.parent / f".browser_profile_{key}"


def installed_browsers() -> List[tuple]:
    """Kurulu desteklenen tarayıcılar: (anahtar, etiket)."""
    return [(b.key, b.label) for b in _supported_browsers() if _first_existing(b.exe_paths)]


def _exe_for_key(browser_key: Optional[str]) -> Optional[str]:
    if not browser_key or browser_key == "auto":
        return None
    for b in _supported_browsers():
        if b.key == browser_key:
            return _first_existing(b.exe_paths)
    return None


def _last_used_profile_name(user_data: Path) -> str:
    try:
        state = json.loads((user_data / "Local State").read_text(encoding="utf-8"))
        return str(state.get("profile", {}).get("last_used") or "Default")
    except Exception:
        return "Default"


def _ai_site_domains() -> List[str]:
    """Hazır yapay zeka sitelerinin kayıtlı alan adları + bunların bilinen betik/CDN alan adları."""
    extra = {"anthropic.com", "openai.com", "x.ai"}
    base = set()
    for site in AI_SITES:
        host = urllib.parse.urlparse(site.url).netloc.lower().removeprefix("www.")
        base.add(".".join(host.split(".")[-2:]))
    return sorted(base | extra)


def allow_ai_sites_in_bridge_profile(profile_dir: Path) -> bool:
    """Köprü profilinde (yalnızca bu kopyada) yapay zeka sitelerinde reklam/izleyici engelleyiciyi kapatır.

    Opera/Opera GX'in yerleşik engelleyicisi, bu sitelerin uygulama betiklerini (ör. Claude'un s.js'i) engelleyip
    sohbetin yanıt almasını bozabiliyor. Kullanıcının asıl tarayıcı profiline dokunulmaz.
    """
    prefs_path = profile_dir / "Default" / "Preferences"
    try:
        data = json.loads(prefs_path.read_text(encoding="utf-8"))
        exceptions = (
            data.setdefault("profile", {}).setdefault("content_settings", {}).setdefault("exceptions", {})
        )
        webkit_now = str(int((time.time() + 11644473600) * 1_000_000))
        for key in ("content_filter_ads", "content_filter_trackers"):
            table = exceptions.setdefault(key, {})
            for domain in _ai_site_domains():
                table[f"[*.]{domain},*"] = {"last_modified": webkit_now, "setting": 1}
        prefs_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return True
    except Exception:
        return False


def seed_bridge_profile_from_default(exe_hint: Optional[str] = None, force: bool = False) -> str:
    """Tarayıcının açık oturumlarını (çerez, yerel depolama) köprü profiline kopyalar.

    Chrome 136+ güvenlik kısıtı nedeniyle CDP, doğrudan varsayılan profil üzerinde çalıştırılamaz; bu yüzden
    oturumlar tek seferlik, YALNIZCA gerekli dosyalar kopyalanarak taşınır (geçmiş, kayıtlı parolalar ve form
    verisi taşınmaz). Tarayıcı açıksa kilitli çerez dosyası kopyalanamayabilir; bu durumda açıkça bildirilir.
    """
    import shutil

    exe = exe_hint or _find_default_browser_executable() or _find_browser_executable()
    if not exe:
        raise RuntimeError("Sistemde desteklenen bir tarayıcı (Chrome, Edge, Opera, Brave, Vivaldi) bulunamadı.")
    info = _browser_for_exe(exe)
    src_root = _default_profile_dir(exe)
    if info is None or src_root is None:
        raise RuntimeError("Seçilen tarayıcının profil dizini bulunamadı.")
    dest = profile_dir_for(info.key)
    cookies_dest = dest / "Default" / "Network" / "Cookies"
    if cookies_dest.is_file() and not force:
        return f"{info.label} köprü profili zaten hazır (tekrar kopyalanmadı)."

    dest.mkdir(parents=True, exist_ok=True)
    src_profile = src_root / _last_used_profile_name(src_root)
    dest_profile = dest / "Default"
    dest_profile.mkdir(parents=True, exist_ok=True)
    problems = []

    for name in _SEED_ROOT_FILES:
        try:
            if (src_root / name).is_file():
                shutil.copy2(src_root / name, dest / name)
        except OSError as exc:
            problems.append(f"{name}: {exc.strerror or exc}")

    for name in _SEED_PROFILE_ITEMS:
        s_item = src_profile / name
        if not s_item.exists():
            continue
        try:
            if s_item.is_dir():
                proc = subprocess.run(
                    ["robocopy", str(s_item), str(dest_profile / name), "/E", "/R:0", "/W:0",
                     "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
                    capture_output=True, text=True, errors="replace", timeout=300,
                )
                if proc.returncode >= 8:
                    problems.append(f"{name} (robocopy {proc.returncode})")
            else:
                (dest_profile / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s_item, dest_profile / name)
        except OSError as exc:
            problems.append(f"{name}: {exc.strerror or exc}")

    if not cookies_dest.is_file():
        hint = f" {info.label} açıkken çerez dosyası kilitli olabilir: tarayıcıyı tamamen kapatıp tekrar deneyin."
        return f"{info.label} profili kısmen kopyalandı, ancak çerez dosyası alınamadı.{hint}"
    allow_ai_sites_in_bridge_profile(dest)
    note = f" (kopyalanamayan: {', '.join(problems)})" if problems else ""
    return f"{info.label} oturumları köprü profiline kopyalandı{note}."


def _find_browser_executable() -> Optional[str]:
    """Kurulu ilk desteklenen Chromium tabanlı tarayıcının yürütülebilir dosyasını bulur."""
    picked = pick_browser("")
    return picked[1] if picked else None


def _browser_label_for_exe(exe_path: str) -> str:
    b = _browser_for_exe(exe_path)
    return b.label if b else Path(exe_path).stem


def _bridge_browser_pid(port: int) -> Optional[int]:
    """CDP portunu dinleyen (köprü) tarayıcı ana sürecinin PID'i (yalnızca Windows)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-NetTCPConnection -LocalPort {int(port)} -State Listen -ErrorAction SilentlyContinue "
             "| Select-Object -First 1).OwningProcess"],
            capture_output=True, text=True, errors="replace", timeout=15,
        ).stdout.strip()
        return int(out) if out.isdigit() else None
    except Exception:
        return None


def focus_bridge_window(port: int = DEFAULT_CDP_PORT) -> bool:
    """Köprü tarayıcısının penceresini geri yükleyip öne getirir (Windows).

    Arka plandaki/küçültülmüş pencerelerde siteler giriş olaylarını yok sayar veya akışı keser; bu yüzden
    denetim sırasında pencere ön planda olmalıdır. Başarılıysa True döner.
    """
    if os.name != "nt":
        return False
    pid = _bridge_browser_pid(port)
    if not pid:
        return False
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found: List[int] = []

        def _cb(hwnd: int, _lp: int) -> bool:
            if user32.IsWindowVisible(hwnd):
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                if owner.value == pid and (rect.right - rect.left) > 300 and user32.GetWindowTextLengthW(hwnd) > 0:
                    found.append(hwnd)
            return True

        user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(_cb), 0)
        if not found:
            return False
        hwnd = found[0]
        user32.ShowWindow(hwnd, 9)   # SW_RESTORE (küçültülmüşse geri getir)
        user32.ShowWindow(hwnd, 3)   # SW_MAXIMIZE
        # Windows'un ön plan kilidini aşmak için Alt tuşu basılıp bırakılır, sonra pencere öne alınır
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.BringWindowToTop(hwnd)
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False


async def _get_cdp_tabs(port: int = DEFAULT_CDP_PORT) -> List[Dict[str, Any]]:
    url = f"http://127.0.0.1:{port}/json"
    async with httpx.AsyncClient(timeout=3.5) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return [t for t in data if isinstance(t, dict) and t.get("type") == "page"]


async def launch_browser_bridge(
    target_url: str = DEFAULT_SITE_URL,
    port: int = DEFAULT_CDP_PORT,
    use_default_profile: bool = False,
    force_seed: bool = False,
    browser_key: Optional[str] = None,
) -> str:
    """Gerçek Chrome/Edge tarayıcısını kalıcı profil ve CDP köprüsüyle başlatır veya açık sekmeyi odaklanır.

    use_default_profile=True ise önce varsayılan tarayıcı profili (oturumlar/çerezler dahil) köprü
    profiline kopyalanır; böylece Gemini, ChatGPT gibi hesap gerektiren sitelerde oturum açık gelir.
    """
    clean_url = target_url.strip() or DEFAULT_SITE_URL
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    try:
        tabs = await _get_cdp_tabs(port)
        domain = urllib.parse.urlparse(clean_url).netloc.lower()
        for t in tabs:
            if domain and domain in str(t.get("url", "")).lower():
                return f"Tarayıcı köprüsü zaten aktif ({t.get('title') or clean_url})."
        async with httpx.AsyncClient(timeout=3.0) as client:
            encoded = urllib.parse.quote(clean_url, safe=":/?&=#")
            await client.put(f"http://127.0.0.1:{port}/json/new?{encoded}")
        return f"Açık tarayıcıda {clean_url} sekmesi açıldı."
    except Exception:
        pass

    exe_path = _exe_for_key(browser_key) or _find_default_browser_executable() or _find_browser_executable()
    if not exe_path:
        raise RuntimeError("Sistemde desteklenen bir tarayıcı (Chrome, Edge, Opera, Brave, Vivaldi) bulunamadı.")
    bridge_info = _browser_for_exe(exe_path)
    bridge_profile = profile_dir_for(bridge_info.key if bridge_info else None)

    if use_default_profile:
        seed_message = await asyncio.to_thread(seed_bridge_profile_from_default, exe_path, force_seed)
    else:
        seed_message = ""

    bridge_profile.mkdir(parents=True, exist_ok=True)
    allow_ai_sites_in_bridge_profile(bridge_profile)
    args = [
        exe_path,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={bridge_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "--start-maximized",
        clean_url,
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(15):
        await asyncio.sleep(0.4)
        try:
            tabs = await _get_cdp_tabs(port)
            if tabs:
                browser_name = _browser_label_for_exe(exe_path)
                await asyncio.to_thread(focus_bridge_window, port)
                base = f"{browser_name} tarayıcı köprüsü başlatıldı ({clean_url})."
                return f"{base} {seed_message}".strip()
        except Exception:
            continue

    raise RuntimeError(
        f"Tarayıcı başlatıldı ancak CDP portu ({port}) yanıt vermedi. "
        "Lütfen açılan tarayıcı penceresini kapatıp tekrar deneyin."
    )


async def _cdp_call(
    ws: Any,
    msg_id: int,
    method: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """CDP WebSocket üzerinden komut gönderir ve yanıtını döndürür."""
    payload = {"id": msg_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(payload))
    deadline = time.perf_counter() + 20.0
    while time.perf_counter() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
        data = json.loads(raw)
        if data.get("id") == msg_id:
            return data.get("result", {})
    return {}


# Metni karşılaştırma için gevşek forma çevirir: markdown linkleri [metin](url) -> metin,
# küçük harf, yalnızca harf ve rakamlar. Site markdown'ı görsel linke çevirse de soru yankısı tanınır.
_LOOSE_JS = r"""
    const __llmGuardLoose = (s) => (s || '')
        .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
        .toLowerCase()
        .replace(/[^\p{L}\p{N}]+/gu, '');
"""

# Mesaj kapsayıcılarındaki metinleri (gevşek form -> adet) sayar. Menü/alt bilgi dahil edilir;
# poll tarafı ayrıca bu bölgeleri aday olmaktan çıkarır.
_COUNT_TEXTS_JS = r"""
    const __LLM_GUARD_MSG_SELECTOR = 'div, p, article, model-response, message-content, chat-message, bard-response';
    const __llmGuardCountTexts = () => {
        const counts = {};
        const nodes = document.querySelectorAll(__LLM_GUARD_MSG_SELECTOR);
        for (let i = 0; i < nodes.length; i++) {
            const raw = nodes[i].textContent || '';
            if (raw.length < 2 || raw.length > 20000) continue;
            const key = __llmGuardLoose(raw);
            if (key) counts[key] = (counts[key] || 0) + 1;
        }
        return counts;
    };
"""


def _loose_text(text: str) -> str:
    """_LOOSE_JS ile aynı gevşek form (Python tarafı yankı kontrolü için)."""
    no_links = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text or "")
    return "".join(ch for ch in no_links.lower() if ch.isalnum())


def _is_prompt_echo(reply: str, prompt: str) -> bool:
    """Okunan 'yanıt' aslında gönderilen sorunun kendisi (veya bir parçası) mı?"""
    r, p = _loose_text(reply), _loose_text(prompt)
    if not r:
        return False
    return r == p or (len(r) >= 30 and r in p)


def _build_send_js(prompt: str) -> str:
    """Sadece ana mesaj bloklarını işaretler (KaTeX/LaTeX span'larına dokunmaz), soruyu yazar ve gönderir."""
    prompt_json = json.dumps(prompt, ensure_ascii=False)
    return f"""
(() => {{
    const promptText = {prompt_json};
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();

    // 1. Gönderimden önceki sayfa metinlerinin anlık görüntüsü ('span' KULLANMA - KaTeX/LaTeX formüllerinde binlerce span olduğu için tarayıcıyı dondurur).
    //    DOM işaretleri sayfa yeniden çizilince kaybolduğu için metin -> adet sayımı tutulur;
    //    poll sırasında yalnızca adedi ARTAN metinler yeni yanıt adayıdır (alt bilgi, önceki soru vb. elenir).
    {_LOOSE_JS}
    {_COUNT_TEXTS_JS}
    window.__llmGuardOldCounts = __llmGuardCountTexts();
    window.__llmGuardPromptNorm = norm(promptText);
    window.__llmGuardPromptLoose = __llmGuardLoose(promptText);
    // Bilinen sitelerde: gönderimden önceki asistan mesajı sayısı (yalnızca YENİ mesaj yanıt sayılır)
    {_ADAPTERS_JS}
    {{
        const __a = __ADAPTERS.find((x) => location.hostname === x.host || location.hostname.endsWith('.' + x.host));
        window.__llmGuardAdapterBase = __a
            ? [...document.querySelectorAll(__a.reply)].filter((e) => (e.innerText || '').trim()).length
            : 0;
    }}

    // 2. Görünür sohbet giriş alanını bul
    const isVisible = (el) => {{
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return r.width > 20 && r.height > 10 && style.visibility !== 'hidden' && style.display !== 'none';
    }};

    const candidates = [
        document.querySelector('#chat-input'),
        ...document.querySelectorAll('textarea:not([disabled])'),
        ...document.querySelectorAll('[contenteditable="true"]'),
        ...document.querySelectorAll('input[type="text"]:not([disabled])')
    ].filter(isVisible);

    if (candidates.length === 0) {{
        return {{ ok: false, error: 'Sayfada aktif bir sohbet yazma kutusu (Mesajınızı yazın...) bulunamadı.' }};
    }}

    const inputEl = candidates[0];
    inputEl.focus();

    // 3. React / Chainlit / Modern framework state uyumlu metin yazma
    if (inputEl.tagName === 'TEXTAREA' || inputEl.tagName === 'INPUT') {{
        const proto = inputEl.tagName === 'TEXTAREA'
            ? window.HTMLTextAreaElement.prototype
            : window.HTMLInputElement.prototype;
        const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (nativeSetter) {{
            nativeSetter.call(inputEl, promptText);
        }} else {{
            inputEl.value = promptText;
        }}
        inputEl.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: promptText }}));
        inputEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }} else {{
        // innerHTML/textContent ile temizleme Trusted Types (Gemini) ve editör çerçeveleri (Quill/ProseMirror) için
        // güvenli değildir: içeriği seçip insertText ile değiştir (editörün kendi durumu bozulmaz).
        document.execCommand('selectAll', false, null);
        document.execCommand('insertText', false, promptText);
    }}

    // 4. Gönder butonuna tıkla veya Enter tuşuna bas
    setTimeout(() => {{
        const btnSelectors = [
            '#chat-submit',
            'button.send-button',
            'button[type="submit"]',
            'button[aria-label*="Send" i]',
            'button[aria-label*="Gönder" i]',
            'button[data-testid*="send" i]'
        ];
        let clicked = false;
        for (const bSel of btnSelectors) {{
            for (const b of document.querySelectorAll(bSel)) {{
                if (isVisible(b) && !b.disabled) {{
                    b.click();
                    clicked = true;
                    break;
                }}
            }}
            if (clicked) break;
        }}

        if (!clicked) {{
            const parent = inputEl.closest('form') || inputEl.parentElement?.parentElement || inputEl.parentElement;
            if (parent) {{
                const nearBtns = [...parent.querySelectorAll('button')].filter(b => isVisible(b) && !b.disabled);
                if (nearBtns.length > 0) {{
                    nearBtns[nearBtns.length - 1].click();
                    clicked = true;
                }}
            }}
        }}

        if (!clicked) {{
            for (const evType of ['keydown', 'keypress', 'keyup']) {{
                inputEl.dispatchEvent(new KeyboardEvent(evType, {{
                    key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true
                }}));
            }}
        }}
    }}, 80);

    return {{ ok: true }};
}})()
"""



# Bilinen sitelere özel yanıt/yeni sohbet kuralları. Genel (metin farkı) yöntem sitelerde sayfa iskeletini
# yanıt sanabildiği için, bu sitelerde asistan mesaj düğümü doğrudan seçilir.
#   reply    : asistan mesajı düğümlerinin CSS seçicisi (son eşleşen yanıttır)
#   busy_text: yanıt metni bu kalıpla başlıyorsa model hâlâ düşünüyor demektir (henüz yanıt değil)
#   new_chat : temiz sohbet için gidilecek adres (her test bağımsız olsun diye)
_SITE_ADAPTERS = [
    {"host": "claude.ai", "reply": '[data-testid="assistant-message"]',
     "busy_text": "^(düşünüyor|thinking|çalışıyor|working|düşünce)", "new_chat": "https://claude.ai/new"},
    {"host": "chatgpt.com", "reply": '[data-message-author-role="assistant"]',
     "busy_text": "^(thinking|düşünüyor)", "new_chat": "https://chatgpt.com/"},
    {"host": "gemini.google.com", "reply": "model-response message-content, .model-response-text",
     "busy_text": "", "new_chat": "https://gemini.google.com/app"},
    {"host": "grok.com", "reply": ".response-content-markdown",
     "busy_text": "", "new_chat": "https://grok.com/"},
    {"host": "chat.deepseek.com", "reply": ".ds-markdown",
     "busy_text": "", "new_chat": "https://chat.deepseek.com/"},
]
_ADAPTERS_JS = "const __ADAPTERS = " + json.dumps(_SITE_ADAPTERS, ensure_ascii=False) + ";\n"

_ADAPTER_POLL_JS = """
    const __adapter = __ADAPTERS.find((a) => location.hostname === a.host || location.hostname.endsWith('.' + a.host));
    if (__adapter) {
        const __els = [...document.querySelectorAll(__adapter.reply)].filter((e) => (e.innerText || '').trim());
        const __last = __els[__els.length - 1];
        const __txt = __last ? (__last.innerText || '').trim() : '';
        const __busyRe = __adapter.busy_text ? new RegExp(__adapter.busy_text, 'i') : null;
        const __thinking = Boolean(__busyRe && __busyRe.test(__txt));
        const __stopBtn = Boolean(document.querySelector(
            'button[aria-label*="Stop" i], button[aria-label*="Durdur" i], button[aria-label*="Yanıtı durdur" i], [data-is-streaming="true"]'
        ));
        const __isNew = __els.length > (window.__llmGuardAdapterBase || 0);
        return { reply: (__thinking || !__isNew) ? '' : __txt, isStreaming: __thinking || __stopBtn, newNodesCount: __els.length };
    }
"""

_POLL_DOM_JS = """
(() => {
    """ + _ADAPTERS_JS + _ADAPTER_POLL_JS + """
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const promptNorm = window.__llmGuardPromptNorm || '';
""" + _LOOSE_JS + _COUNT_TEXTS_JS + """
    const promptLoose = window.__llmGuardPromptLoose || __llmGuardLoose(promptNorm);
    const oldCounts = window.__llmGuardOldCounts || {};
    // Gönderimden önce sayfada olan uzun metinler (alt bilgi, önceki mesajlar). Bunları İÇEREN bir kapsayıcı
    // asistan yanıtı değildir (örn. kaydırma düğmesi belirdiği için metni değişen sayfa iskeleti).
    const oldLongKeys = Object.keys(oldCounts).filter((k) => k.length >= 40);

    // Gönderimden sonra adedi ARTAN metinler yenidir (sayfa yeniden çizilse de eski metinler elenir)
    const nowCounts = __llmGuardCountTexts();
    const allNew = [...document.querySelectorAll(__LLM_GUARD_MSG_SELECTOR)].filter((el) => {
        const raw = el.textContent || '';
        if (raw.length < 2 || raw.length > 20000) return false;
        const key = __llmGuardLoose(raw);
        return key && (nowCounts[key] || 0) > (oldCounts[key] || 0);
    });
    // Sadece yeni mesaj düğümlerinin SON 25 tanesini incele (LaTeX/KaTeX span'larını tarama!)
    const recentNodes = allNew.slice(-25);

    const timeRegex = /^\\d{1,2}:\\d{2}$/;
    const candidates = [];

    for (const el of recentNodes) {
        const rawText = (el.textContent || '').trim();
        if (!rawText || rawText.length < 2) continue;
        if (timeRegex.test(rawText)) continue;
        // Site menüsü / alt bilgi / başlık bölgeleri asla asistan yanıtı değildir
        if (el.closest('footer, nav, header, [role="contentinfo"], [role="navigation"], [role="banner"]')) continue;
        if (el.querySelector('footer, nav, [role="contentinfo"], [role="navigation"], textarea, [contenteditable="true"]')) continue;
        const elLoose = __llmGuardLoose(rawText);
        if (oldLongKeys.some((k) => k !== elLoose && elLoose.includes(k))) continue;

        // Görünür metni al ve sondaki saat damgasını (örn: 17:03) temizle
        const inner = (el.innerText || rawText).trim();
        const lines = inner.split('\\n').map(l => l.trim()).filter(l => l && !timeRegex.test(l));
        const cleanText = lines.join('\\n').trim();
        if (!cleanText) continue;

        const cleanNorm = norm(cleanText);
        if (!cleanNorm) continue;

        // Kullanıcının kendi mavi soru balonunu veya hem soruyu hem cevabı içeren dev ana kapsayıcıyı atla
        if (
            cleanNorm === promptNorm ||
            promptNorm.includes(cleanNorm) ||
            (promptNorm.length > 15 && cleanNorm.includes(promptNorm))
        ) {
            continue;
        }
        // Gevşek karşılaştırma: site markdown linkini görsel linke çevirdiğinde de soru yankısını tanı
        const cleanLoose = __llmGuardLoose(cleanText);
        if (
            cleanLoose === promptLoose ||
            (cleanLoose.length >= 30 && promptLoose.includes(cleanLoose)) ||
            (promptLoose.length > 15 && cleanLoose.includes(promptLoose))
        ) {
            continue;
        }

        if (cleanNorm === 'Sohbeti Temizle' || cleanNorm === 'Sohbet') continue;
        candidates.push(cleanText);
    }

    let latestReply = '';
    if (candidates.length > 0) {
        // En kapsamlı yeni asistan mesaj balonunu seç
        latestReply = candidates[0];
        for (const c of candidates) {
            if (c.length >= latestReply.length) {
                latestReply = c;
            }
        }
    }

    const isStreaming = Boolean(
        document.querySelector('button[aria-label*="Stop" i], button[aria-label*="Durdur" i], #stop-button, .streaming')
    );

    return {
        reply: latestReply,
        isStreaming: isStreaming,
        newNodesCount: recentNodes.length
    };
})()
"""


_CHECK_INPUT_READY_JS = """
(() => {
    const isVisible = (el) => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return r.width > 20 && r.height > 10 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const candidates = [
        document.querySelector('#chat-input'),
        ...document.querySelectorAll('textarea:not([disabled])'),
        ...document.querySelectorAll('[contenteditable="true"]'),
        ...document.querySelectorAll('input[type="text"]:not([disabled])')
    ].filter(isVisible);
    return candidates.length > 0;
})()
"""

_DETECT_BLOCKER_JS = """
(() => {
    const isVisible = (el) => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return r.width > 30 && r.height > 10 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const haystack = (document.body ? (document.body.innerText || '') : '').toLowerCase();
    const url = (location.href || '').toLowerCase();

    // 1. Giriş duvarı: URL, buton veya kapsayılabilir başlık metninde oturum açma isteği
    const loginTexts = [
        'log in', 'login', 'sign in', 'sign up to chat', 'giriş yap', 'giris yap',
        'oturum aç', 'oturum ac', 'üye ol', 'uye ol', 'kaydol', 'giriş yapın',
        'devam etmek için giriş', 'log in to continue', 'create an account'
    ];
    let loginVisible = /([/]login|[/]signin|[/]sign_in|[/]sign-in|[/]auth|[/]giris)/.test(url);
    if (!loginVisible) {
        const btnTexts = [...document.querySelectorAll('button, a, [role="button"], h1, h2, h3, p')]
            .filter(isVisible)
            .map(b => (b.innerText || b.getAttribute('aria-label') || '').toLowerCase());
        loginVisible = btnTexts.some(t => t && loginTexts.some(lt => t === lt || t.includes(lt)));
    }

    // 2. Cloudflare / doğrulama sorgusu
    const cfVisible = Boolean(
        document.querySelector('#cf-challenge-running, .cf-browser-verification, [id*="cf-"], [class*="cf-"]')
    ) || haystack.includes('checking your browser') || haystack.includes('doğrulama') && haystack.includes('bekleyin');

    // 3. Sohbet kutusu gerçekten var mı (engel olmadan da bulunamama durumu)
    const inputReady = (() => {
        const candidates = [
            document.querySelector('#chat-input'),
            ...document.querySelectorAll('textarea:not([disabled])'),
            ...document.querySelectorAll('[contenteditable="true"]'),
            ...document.querySelectorAll('input[type="text"]:not([disabled])')
        ].filter(isVisible);
        return candidates.length > 0;
    })();

    return { loginWall: loginVisible, cloudflare: cfVisible, inputReady, url: location.href || '' };
})()
"""

_BLOCKER_HINT_TR = (
    "Bu site hesap girişi istiyor. Köprü tarayıcısı kendi özel profiliyle açıldığı için henüz bu sitede "
    "oturum açık değil. İki yol var: (1) Açılan köprü penceresinde siteye bir kez giriş yapın; profil "
    "kaydedildiği için sonraki çalıştırmalarda giriş sorulmaz. (2) Arayüzde '👤 Varsayılan Profilimden Kopyala' "
    "anahtarını açıp (normal tarayıcınız kapalıyken) '🌐 Tarayıcıyı Aç' deyin; tarayıcınızdaki açık oturumlar "
    "köprü profiline bir kez kopyalanır. (Chrome 136+ güvenlik kısıtı nedeniyle ana profil doğrudan kullanılamaz.)"
)

_LOGIN_BANNER_PHRASES = (
    "oturum açın", "oturum ac", "giriş yapın", "giris yapin", "giriş yap", "kaydolun", "hesap oluşturun",
    "sign in", "log in", "login to", "sign up", "create an account", "to continue", "devam etmek için",
    "geçmişinizi kaydetmek", "save your history",
    "tanımlama bilgileri", "çerez", "cookie", "accept all", "tümünü kabul",  # çerez onayı penceresi de yanıt değildir
)


def _looks_like_login_banner(text: str) -> bool:
    """Okunan 'yanıt' aslında kısa bir oturum açma/kayıt çağrısı mı (gerçek bir cevap değil)?"""
    t = (text or "").strip().lower()
    return 0 < len(t) <= 400 and any(p in t for p in _LOGIN_BANNER_PHRASES)

_SMART_CLEAR_CHAT_JS = """
(() => {
    """ + _ADAPTERS_JS + """
    const __adapterNew = __ADAPTERS.find((a) => location.hostname === a.host || location.hostname.endsWith('.' + a.host));
    if (__adapterNew && __adapterNew.new_chat) {
        setTimeout(() => { try { window.location.href = __adapterNew.new_chat; } catch (e) {} }, 50);
        return { mode: 'async_reload' };
    }
    // 1. Öncelikle sayfa içindeki 'Sohbeti Temizle' / 'Yeni Sohbet' / 'New Chat' butonunu bul ve tıkla (Cloudflare/F5 takılmasını %100 önler)
    const btns = [...document.querySelectorAll('button, a, [role="button"]')];
    for (const b of btns) {
        const t = (b.innerText || b.getAttribute('aria-label') || '').trim().toLowerCase();
        if (
            t === 'sohbeti temizle' ||
            t === 'yeni sohbet' ||
            t === 'new chat' ||
            t === 'clear chat' ||
            t === 'sohbeti sıfırla'
        ) {
            try {
                b.click();
                // Onay penceresi çıkarsa ('Evet', 'Temizle', 'Onayla') 120ms sonra ona da tıkla
                setTimeout(() => {
                    const confirmBtns = [...document.querySelectorAll('button')];
                    for (const cb of confirmBtns) {
                        const ct = (cb.innerText || '').trim().toLowerCase();
                        if (ct === 'evet' || ct === 'onayla' || ct === 'temizle' || ct === 'confirm' || ct === 'yes') {
                            try { cb.click(); } catch (e) {}
                        }
                    }
                }, 120);
                return { mode: 'in_page_button' };
            } catch (e) {}
        }
    }

    // 2. Eğer temizle butonu yoksa CDP'yi kilitlemeden asenkron yumuşak yenileme başlat
    setTimeout(() => {
        try { window.location.reload(); } catch (e) {}
    }, 50);
    return { mode: 'async_reload' };
})()
"""


# Metin giriş kutusunda hâlâ gönderilmemiş prompt var mı ve gönder düğmesi nerede? (güvenilir "gerçek" tıklama için)
_PENDING_JS = r"""
(() => {
    const snippet = (window.__llmGuardPromptNorm || '').slice(0, 20).toLowerCase();
    const isVisible = (el) => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const st = window.getComputedStyle(el);
        return r.width > 20 && r.height > 10 && st.visibility !== 'hidden' && st.display !== 'none';
    };
    const inputs = [
        ...document.querySelectorAll('textarea:not([disabled])'),
        ...document.querySelectorAll('[contenteditable="true"]'),
        ...document.querySelectorAll('input[type="text"]:not([disabled])')
    ].filter(isVisible);
    const text = inputs.map((e) => (e.value || e.innerText || '')).join(' ').replace(/\s+/g, ' ').trim().toLowerCase();
    const pending = Boolean(snippet) && text.includes(snippet);
    let btn = null;
    const sels = ['#chat-submit', 'button.send-button', 'button[type="submit"]', 'button[aria-label*="Send" i]',
                  'button[aria-label*="Gönder" i]', 'button[data-testid*="send" i]'];
    for (const sel of sels) {
        for (const b of document.querySelectorAll(sel)) {
            const r = b.getBoundingClientRect();
            if (isVisible(b) && !b.disabled && b.getAttribute('aria-disabled') !== 'true') {
                btn = { x: r.x + r.width / 2, y: r.y + r.height / 2 };
                break;
            }
        }
        if (btn) break;
    }
    return { pending, btn };
})()
"""


async def _submit_if_pending(ws: Any, msg_id: int) -> int:
    """Bazı siteler (ör. Gemini) betikle üretilen (güvenilmeyen) tıklamaları yok sayar. Prompt gönderilmeden
    kutuda kaldıysa önce gerçek Enter tuşu, olmazsa gerçek fare tıklaması gönderir."""
    for attempt in ("enter", "mouse"):
        await asyncio.sleep(1.2)
        res = await _cdp_call(ws, msg_id, "Runtime.evaluate", {"expression": _PENDING_JS, "returnByValue": True})
        msg_id += 1
        info = res.get("result", {}).get("value", {})
        if not isinstance(info, dict) or not info.get("pending"):
            return msg_id
        if attempt == "enter":
            for typ in ("keyDown", "keyUp"):
                params = {"type": typ, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}
                if typ == "keyDown":
                    params["text"] = "\r"
                await _cdp_call(ws, msg_id, "Input.dispatchKeyEvent", params)
                msg_id += 1
        else:
            btn = info.get("btn")
            if isinstance(btn, dict):
                for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
                    params = {"type": typ, "x": btn["x"], "y": btn["y"], "button": "left", "clickCount": 1}
                    await _cdp_call(ws, msg_id, "Input.dispatchMouseEvent", params)
                    msg_id += 1
    return msg_id


async def query_browser_bridge(
    prompt: str,
    target_url: str = DEFAULT_SITE_URL,
    port: int = DEFAULT_CDP_PORT,
    timeout_sec: float = 55.0,
    refresh_after: bool = True,
    use_default_profile: bool = False,
    browser_key: Optional[str] = None,
) -> str:
    """Açık Chrome/Edge sekmesine CDP üzerinden bağlanır, soruyu yazar, cevabı okur ve sohbeti temizler."""
    async with _BROWSER_LOCK:
        clean_url = target_url.strip() or DEFAULT_SITE_URL
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url

        try:
            tabs = await _get_cdp_tabs(port)
        except Exception:
            await launch_browser_bridge(
                clean_url, port, use_default_profile=use_default_profile, browser_key=browser_key
            )
            await asyncio.sleep(2.5)
            tabs = await _get_cdp_tabs(port)

        if not tabs:
            raise RuntimeError("Açık tarayıcı sekmesi bulunamadı. Lütfen '🌐 Tarayıcıyı Aç' butonuna tıklayın.")

        domain = urllib.parse.urlparse(clean_url).netloc.lower()
        target_tab = None
        for t in tabs:
            tab_url = str(t.get("url", "")).lower()
            if domain and domain in tab_url:
                target_tab = t
                break
        if not target_tab:
            for t in tabs:
                if not str(t.get("url", "")).startswith(("devtools://", "chrome://", "edge://")):
                    target_tab = t
                    break
        if not target_tab:
            target_tab = tabs[0]

        ws_url = target_tab.get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("Tarayıcı sekmesinin CDP WebSocket adresi alınamadı.")

        msg_id = 1
        try:
            async with websockets.connect(
                ws_url,
                max_size=16 * 1024 * 1024,
                open_timeout=10.0,
                ping_interval=None,
            ) as ws:
                await _cdp_call(ws, msg_id, "Runtime.enable")
                msg_id += 1

                # Önceki sorudan sonra sayfa yenilendiyse sohbet kutusunun hazır olmasını bekle (en fazla 10 sn)
                input_ready = False
                for _ in range(20):
                    try:
                        ready_res = await _cdp_call(
                            ws,
                            msg_id,
                            "Runtime.evaluate",
                            {"expression": _CHECK_INPUT_READY_JS, "returnByValue": True},
                        )
                        msg_id += 1
                        if ready_res.get("result", {}).get("value") is True:
                            input_ready = True
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)

                # Giriş duvarı / Cloudflare gibi engelleri tespit et ve net hata ver
                blocker_info: Dict[str, Any] = {}
                try:
                    blocker_res = await _cdp_call(
                        ws,
                        msg_id,
                        "Runtime.evaluate",
                        {"expression": _DETECT_BLOCKER_JS, "returnByValue": True},
                    )
                    msg_id += 1
                    val = blocker_res.get("result", {}).get("value", {})
                    if isinstance(val, dict):
                        blocker_info = val
                except Exception:
                    pass

                if blocker_info.get("cloudflare") and not blocker_info.get("loginWall"):
                    raise RuntimeError(
                        "Sayfa Cloudflare doğrulamasıyla karşılaştı. Köprü penceresinde doğrulamayı "
                        "manuel tamamlayın ve denetimi tekrar çalıştırın."
                    )
                if blocker_info.get("loginWall") and not blocker_info.get("inputReady"):
                    raise RuntimeError(_BLOCKER_HINT_TR)
                if not input_ready and not blocker_info.get("inputReady"):
                    raise RuntimeError(
                        "Sayfada aktif bir sohbet yazma kutusu (Mesajınızı yazın...) bulunamadı. "
                        "Hedef sitenin sohbet ekranında olduğundan emin olun."
                    )

                await asyncio.to_thread(focus_bridge_window, port)
                # Sekme arka plandaysa (köprü penceresi odakta değilse) bazı siteler giriş olaylarını yok sayar
                try:
                    await _cdp_call(ws, msg_id, "Page.bringToFront", {})
                except Exception:
                    pass
                msg_id += 1

                send_res = await _cdp_call(
                    ws,
                    msg_id,
                    "Runtime.evaluate",
                    {"expression": _build_send_js(prompt), "returnByValue": True},
                )
                msg_id += 1

                val = send_res.get("result", {}).get("value", {})
                if isinstance(val, dict) and not val.get("ok", False):
                    raise RuntimeError(str(val.get("error", "Sohbet kutusuna yazılamadı.")))

                msg_id = await _submit_if_pending(ws, msg_id)

                deadline = time.perf_counter() + timeout_sec
                last_dom_reply = ""
                stable_since: Optional[float] = None
                final_reply: Optional[str] = None

                while time.perf_counter() < deadline:
                    await asyncio.sleep(0.5)

                    try:
                        poll_res = await _cdp_call(
                            ws,
                            msg_id,
                            "Runtime.evaluate",
                            {"expression": _POLL_DOM_JS, "returnByValue": True},
                        )
                        msg_id += 1
                    except Exception:
                        continue

                    dom_info = poll_res.get("result", {}).get("value", {})
                    if isinstance(dom_info, dict):
                        curr_reply = str(dom_info.get("reply") or "").strip()
                        is_streaming = bool(dom_info.get("isStreaming", False))

                        if curr_reply:
                            if curr_reply != last_dom_reply:
                                last_dom_reply = curr_reply
                                stable_since = time.perf_counter()
                            elif not is_streaming and stable_since and (time.perf_counter() - stable_since) >= 1.8:
                                final_reply = last_dom_reply
                                break

                if not final_reply and last_dom_reply:
                    final_reply = last_dom_reply

                if not final_reply:
                    # Yanıt gelmedi: giriş duvarı sonradan mı çıktı diye bir kez kontrol et
                    try:
                        late_blocker = await _cdp_call(
                            ws,
                            msg_id,
                            "Runtime.evaluate",
                            {"expression": _DETECT_BLOCKER_JS, "returnByValue": True},
                        )
                        late_val = late_blocker.get("result", {}).get("value", {})
                        if isinstance(late_val, dict) and late_val.get("loginWall"):
                            raise RuntimeError(
                                "Mesaj gönderildi ancak site giriş duvarına takıldı. " + _BLOCKER_HINT_TR
                            )
                    except RuntimeError:
                        raise
                    except Exception:
                        pass

                if final_reply:
                    final_reply = clean_chat_reply(final_reply) or final_reply

                # Okunan metin kısa bir "oturum açın" çağrısıysa bu sitenin yanıtı değil, giriş duvarıdır
                if final_reply and _looks_like_login_banner(final_reply):
                    raise RuntimeError("Site yanıt yerine bir oturum açma isteği gösterdi. " + _BLOCKER_HINT_TR)

                # Güvenlik ağı: okunan metin sorunun kendisiyse bu bir yanıt değildir (güvenli sayılmamalı)
                echo_detected = bool(final_reply) and _is_prompt_echo(final_reply or "", prompt)
                if echo_detected:
                    final_reply = None

                # Yanıt alınamasa da sohbeti temizle: aksi halde sonraki test bu sorunun kalıntısını okuyabilir
                if refresh_after:
                    try:
                        clear_res = await _cdp_call(
                            ws,
                            msg_id,
                            "Runtime.evaluate",
                            {"expression": _SMART_CLEAR_CHAT_JS, "returnByValue": True},
                        )
                        msg_id += 1
                        clear_mode = (
                            clear_res.get("result", {}).get("value", {}).get("mode", "")
                            if isinstance(clear_res.get("result", {}).get("value"), dict)
                            else ""
                        )
                        # Sayfa içi buton tıklandıysa 0.4 sn yeterli; F5 atıldıysa 1.5 sn bekle
                        await asyncio.sleep(0.45 if clear_mode == "in_page_button" else 1.5)
                    except Exception:
                        pass

                if final_reply:
                    return final_reply

                if echo_detected:
                    raise RuntimeError(
                        "Asistan yanıtı yerine gönderilen sorunun kendisi okundu; yanıt güvenilir şekilde ayrıştırılamadı."
                    )
                raise RuntimeError(
                    f"Tarayıcıda mesaj gönderildi ancak {timeout_sec:.0f} saniye içinde yeni bir asistan yanıtı algılanamadı."
                )
        except Exception as exc:
            err_msg = str(exc).strip() or type(exc).__name__
            raise RuntimeError(f"Tarayıcı köprüsü iletişim hatası ({err_msg})")
