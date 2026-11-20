"""Renk paleti, dosya yolları ve tablo satırı gösterimi."""
from pathlib import Path

from src.dataset_hub import DATASETS_DIR
from src.models import EvaluationResult

ROOT_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = ROOT_DIR / "assets"
BARN_OWL_SPRITE_PATH = ASSETS_DIR / "barn_owl_sprite.png"
KALI_OWL_LOGO_PATH = ASSETS_DIR / "kali_owl_logo.png"
DEFAULT_DATASET_PATH = DATASETS_DIR / "all_combined_master.json"
ICON_PATH = ROOT_DIR / "app_icon.ico"

# Özel Cyber-Owl Renk Paleti
THEME = {
    "bg_main": "#141118",
    "bg_panel": "#1B1521",
    "bg_card": "#231C2B",
    "bg_input": "#16111C",
    "border": "#402B47",
    "accent": "#8350C4",
    "accent_hover": "#693B9E",
    "secondary": "#7392B5",
    "text_main": "#C9E0EB",
    "text_dim": "#8FA8BE",
    "pass": "#34D399",
    "fail": "#F87171",
    "warn": "#FBBF24",
}



_ROW_DISPLAY = {
    "passed": ("✅ GÜVENLİ", "pass"),
    "violated": ("🚨 İHLAL", "fail"),
    "error": ("⚠️ HATA", "warn"),
    "cancelled": ("⏹️ İPTAL", "warn"),
}


def row_display(res: EvaluationResult) -> tuple[str, str]:
    """Sonucun tablodaki durum metni ve satır türü (pass / fail / warn).

    ✔ = elle doğrulandı, 🔎 = otomatik karar, elle doğrulanması önerilir.
    """
    label, kind = _ROW_DISPLAY[res.effective_outcome]
    if res.manual_outcome:
        label += " ✔"
    elif res.needs_review:
        label += " 🔎"
    return label, kind
