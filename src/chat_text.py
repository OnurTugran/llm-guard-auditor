"""Web sohbet sitelerinden okunan yanıt metnini temizleyen yardımcılar (arayüzden bağımsız, test edilebilir)."""
import re
from typing import List

_ICON_CHARS = re.compile("[-]")  # Özel Kullanım Alanı: sitelerin simge yazı tipi karakterleri
_UI_NOISE_LINE = re.compile(
    r"^(claude (yanıt verdi|responded)\b.*|şimdi|now|just now|"
    r"\d+\s*(saniye|dakika|saat|second|minute|hour)s?\s*(önce|ago)|"
    r"kopyala|copy|yanıtı kopyala|retry|tekrar dene)$",
    re.IGNORECASE,
)


def clean_chat_reply(text: str) -> str:
    """Yanıt kutusuna eklenen arayüz kalıntılarını temizler: simge karakterleri, ekran okuyucu satırı,
    zaman damgası, kopyala düğmesi metni ve art arda tekrarlanan satırlar. Gerçek yanıt metnine dokunmaz."""
    no_icons = _ICON_CHARS.sub("", text or "")
    lines = [ln.strip() for ln in no_icons.splitlines()]
    kept = [ln for ln in lines if ln and not _UI_NOISE_LINE.match(ln)]
    out: List[str] = []
    for ln in kept:
        if not out or ln != out[-1]:
            out.append(ln)
    return "\n".join(out).strip()
