"""Kullanıcının yapıştırdığı başlık/çerez metnini ayrıştırır (arayüzden bağımsız, test edilebilir)."""
import json


def parse_headers_or_cookie_input(raw_text: str) -> dict[str, str]:
    """Kullanıcı JSON formatında da yazsa düz Cookie metni de yapıştırsa güvenli şekilde başlık sözlüğüne çevirir."""
    cleaned = raw_text.strip()
    if not cleaned:
        return {}
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except Exception:
        pass
    # Eğer düz metin yapıştırıldıysa (örn: oturum=...; access_token=...) doğrudan Cookie başlığına sar
    if ":" in cleaned and ";" not in cleaned.split("\n")[0]:
        out: dict[str, str] = {}
        for line in cleaned.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip().strip('"')] = v.strip().strip('",')
        if out:
            return out
    return {"Cookie": cleaned.strip('"')}
