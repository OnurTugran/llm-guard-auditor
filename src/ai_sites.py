"""Tarayıcı köprüsü için hazır, bilinen yapay zeka sohbet siteleri.

Kullanıcı bu sitelerden birini seçer; araç kullanıcının kendi tarayıcısını ve (isteğe bağlı) kendi
oturum açmış hesabını kullanarak sohbet kutusuna prompt yazar ve yanıtı okur. Hiçbir siteye özel
kimlik doğrulama atlatması yoktur; yalnızca kullanıcının zaten açtığı oturum kullanılır.

Not: Her sitenin kullanım şartları otomatik erişimi kısıtlıyor olabilir. Yalnızca kendi hesabınızla,
düşük hacimle ve izin verilen ölçüde kullanın.
"""
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse


@dataclass(frozen=True)
class AISite:
    name: str
    url: str
    login_note: str


CUSTOM_SITE_NAME = "Özel adres (kendim yazarım)"

AI_SITES: List[AISite] = [
    AISite("ChatGPT", "https://chatgpt.com", "Hesapsız da açılır; geçmiş için OpenAI hesabı"),
    AISite("Google Gemini", "https://gemini.google.com", "Google hesabı gerekir"),
    AISite("Claude", "https://claude.ai", "Anthropic hesabı gerekir"),
    AISite("Microsoft Copilot", "https://copilot.microsoft.com", "Hesapsız açılır; Microsoft hesabı isteğe bağlı"),
    AISite("Perplexity", "https://www.perplexity.ai", "Hesapsız açılır; hesap isteğe bağlı"),
    AISite("Grok", "https://grok.com", "X/xAI hesabı gerekebilir"),
    AISite("DeepSeek", "https://chat.deepseek.com", "Hesap gerekir"),
    AISite("Mistral Le Chat", "https://chat.mistral.ai", "Hesapsız açılır; hesap isteğe bağlı"),
    AISite("Meta AI", "https://www.meta.ai", "Meta/Facebook hesabı gerekebilir"),
]

DEFAULT_SITE_URL = AI_SITES[0].url


def site_names() -> List[str]:
    """Açılır menüde gösterilecek adlar (en sonda özel adres seçeneği)."""
    return [s.name for s in AI_SITES] + [CUSTOM_SITE_NAME]


def get_site(name: str) -> Optional[AISite]:
    for s in AI_SITES:
        if s.name == name:
            return s
    return None


def site_for_url(url: str) -> Optional[AISite]:
    """Verilen adresin bilinen sitelerden hangisine ait olduğunu (alan adına göre) bulur."""
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")
    for s in AI_SITES:
        if urlparse(s.url).netloc.lower().removeprefix("www.") == host:
            return s
    return None
