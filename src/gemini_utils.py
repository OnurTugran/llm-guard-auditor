"""Gemini REST çağrıları için paylaşılan yardımcılar.

Sabit model adları Google tarafından emekli edildiğinde (404) uygulamanın sessizce
çökmesini önlemek amacıyla ListModels uç noktasıyla dinamik model keşfi yapar.
"""
import asyncio
import re
from typing import Any, Dict, List, Optional
import httpx

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


async def list_gemini_models(
    api_key: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> List[str]:
    """ListModels uç noktasından generateContent destekleyen güncel model kimliklerini çeker.

    Döndürülen kimlikler 'models/' öneki olmadan, örn. 'gemini-3.8-flash'.
    """
    url = f"{GEMINI_API_BASE}/models?pageSize=200"
    req_headers = {"x-goog-api-key": api_key.strip()}
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=10.0)
    try:
        resp = await client.get(url, headers=req_headers, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        ids: List[str] = []
        for m in data.get("models", []):
            methods = m.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            name = str(m.get("name", ""))
            if name.startswith("models/"):
                name = name[len("models/"):]
            if name:
                ids.append(name)
        return ids
    finally:
        if owns_client:
            await client.aclose()


def rank_gemini_models(ids: List[str], prefer_pro: bool = False) -> List[str]:
    """ListModels çıktısını denenecek aday sırasına dizer: önce flash (veya pro), yüksek sürüm öncelikli."""
    def score(model_id: str) -> tuple:
        nums = re.findall(r"(\d+)\.(\d+)", model_id)
        major, minor = (int(nums[0][0]), int(nums[0][1])) if nums else (0, 0)
        low = model_id.lower()
        if prefer_pro:
            kind = 0 if "pro" in low else (1 if "flash" in low else 2)
        else:
            kind = 0 if "flash" in low else (1 if "pro" in low else 2)
        return (kind, -major, -minor)

    usable = [
        m for m in ids
        if not any(tag in m.lower() for tag in ("embedding", "image", "live", "a2a", "tts", "diffusion"))
    ]
    return sorted(usable, key=score)


async def gemini_generate_with_discovery(
    *,
    api_key: str,
    payload: Dict[str, Any],
    static_candidates: List[str],
    http_client: Optional[httpx.AsyncClient] = None,
    timeout: float = 10.0,
    max_fresh_attempts: int = 3,
) -> str:
    """generateContent çağırır; sabit adaylar başarısızsa ListModels ile keşfedilen güncel modelleri dener.

    429/5xx alındığında aynı modeli üstel geri çekilme ile tekrar dener.
    Kimlik/doğrulama hatalarında (401/403) denemeyi hemen keser.
    Tümü başarısızsa son hata ile RuntimeError yükseltir.
    """
    cleaned = [m.replace("gemini/", "").replace("models/", "").strip() for m in static_candidates]
    seen: List[str] = []
    for m in cleaned:
        if m and m not in seen:
            seen.append(m)

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout)
    last_err = ""

    async def _try_model(model_id: str) -> Optional[str]:
        nonlocal last_err
        url = f"{GEMINI_API_BASE}/models/{model_id}:generateContent"
        for attempt in range(3):
            resp = await client.post(url, json=payload, headers=req_headers, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            last_err = f"{model_id} -> HTTP {resp.status_code}: {resp.text[:160]}"
            if resp.status_code in _RETRYABLE_STATUS and attempt < 2:
                await asyncio.sleep(1.5 * (2 ** attempt))
                continue
            break
        return None

    try:
        req_headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key.strip(),
        }
        tried = set()
        for mod in seen:
            tried.add(mod)
            result = await _try_model(mod)
            if result is not None:
                return result

        # Statik adaylar başarısız: ListModels ile güncel modelleri keşfet
        try:
            fresh_ids = await list_gemini_models(api_key, http_client=client)
        except Exception as exc:
            fresh_ids = []
            last_err += f" | ListModels başarısız: {exc}"

        for mod in rank_gemini_models(fresh_ids)[:max_fresh_attempts]:
            if mod in tried:
                continue
            result = await _try_model(mod)
            if result is not None:
                return result

        raise RuntimeError(last_err or "Gemini yanıt vermedi.")
    finally:
        if owns_client:
            await client.aclose()
