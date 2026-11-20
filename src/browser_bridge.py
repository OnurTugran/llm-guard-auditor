import asyncio
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

from src.ai_sites import DEFAULT_SITE_URL

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


def seed_bridge_profile_from_default(exe_hint: Optional[str] = None, force: bool = False) -> str:
    """Varsayılan tarayıcı profilini (çerezler ve oturumlarla birlikte) köprü profiline kopyalar.

    Chrome 136+ güvenlik kısıtı nedeniyle CDP, doğrudan varsayılan profil üzerinde çalıştırılamaz;
    bu yüzden oturumları taşımak için tek seferlik profil kopyalama yapılır. Kilitli dosyalar atlanır
    (tarayıcı açıksa çerezlerin bir kısmı kopyalanamayabilir; kopyalama öncesi tarayıcıyı kapatmak önerilir).
    """
    exe = exe_hint or _find_default_browser_executable() or _find_browser_executable()
    if not exe:
        raise RuntimeError("Sistemde Google Chrome veya Microsoft Edge bulunamadı.")
    src = _default_profile_dir(exe)
    if src is None:
        raise RuntimeError("Varsayılan tarayıcının profil dizini bulunamadı.")
    if ( _PROFILE_DIR / "Default" ).is_dir() and not force:
        return "Köprü profili zaten hazır (tekrar kopyalanmadı)."

    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    cache_dirs = [
        "Cache", "Code Cache", "GPUCache", "Media Cache", "Service Worker",
        "Crashpad", "component_crx_cache", "GrShaderCache", "ShaderCache",
        "browser-metrics", "optimizationguide_hintcachestore",
    ]
    cmd = [
        "robocopy", str(src), str(_PROFILE_DIR),
        "/E", "/COPY:DAT", "/DCOPY:DAT", "/R:0", "/W:0",
        "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
        "/XD", *cache_dirs,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode >= 8:
        raise RuntimeError(f"Profil kopyalama başarısız (robocopy çıkış kodu {proc.returncode}).")
    skipped_locked = proc.returncode in (1, 3, 5, 7)
    suffix = (
        " Kilitli dosyalar atlandı; çerezlerin tamamı taşınmadıysa tarayıcıyı kapatıp tekrar deneyin."
        if skipped_locked else ""
    )
    return f"Varsayılan profil köprüye kopyalandı ({src}).{suffix}"


def _find_browser_executable() -> Optional[str]:
    """Kurulu ilk desteklenen Chromium tabanlı tarayıcının yürütülebilir dosyasını bulur."""
    picked = pick_browser("")
    return picked[1] if picked else None


def _browser_label_for_exe(exe_path: str) -> str:
    b = _browser_for_exe(exe_path)
    return b.label if b else Path(exe_path).stem


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

    exe_path = _find_default_browser_executable() or _find_browser_executable()
    if not exe_path:
        raise RuntimeError("Sistemde Google Chrome veya Microsoft Edge bulunamadı.")

    if use_default_profile:
        seed_message = await asyncio.to_thread(seed_bridge_profile_from_default, exe_path, force_seed)
    else:
        seed_message = ""

    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        exe_path,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        clean_url,
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(15):
        await asyncio.sleep(0.4)
        try:
            tabs = await _get_cdp_tabs(port)
            if tabs:
                browser_name = _browser_label_for_exe(exe_path)
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
        inputEl.innerHTML = '';
        document.execCommand('insertText', false, promptText);
        inputEl.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: promptText }}));
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


_POLL_DOM_JS = """
(() => {
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
    let loginVisible = /(\\/login|\\/signin|\\/auth|\\/giris)/.test(url);
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
)


def _looks_like_login_banner(text: str) -> bool:
    """Okunan 'yanıt' aslında kısa bir oturum açma/kayıt çağrısı mı (gerçek bir cevap değil)?"""
    t = (text or "").strip().lower()
    return 0 < len(t) <= 200 and any(p in t for p in _LOGIN_BANNER_PHRASES)

_SMART_CLEAR_CHAT_JS = """
(() => {
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


async def query_browser_bridge(
    prompt: str,
    target_url: str = DEFAULT_SITE_URL,
    port: int = DEFAULT_CDP_PORT,
    timeout_sec: float = 55.0,
    refresh_after: bool = True,
    use_default_profile: bool = False,
) -> str:
    """Açık Chrome/Edge sekmesine CDP üzerinden bağlanır, soruyu yazar, cevabı okur ve sohbeti temizler."""
    async with _BROWSER_LOCK:
        clean_url = target_url.strip() or DEFAULT_SITE_URL
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url

        try:
            tabs = await _get_cdp_tabs(port)
        except Exception:
            await launch_browser_bridge(clean_url, port, use_default_profile=use_default_profile)
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

                if blocker_info.get("cloudflare"):
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
