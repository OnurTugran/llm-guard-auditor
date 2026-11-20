"""Baykuş maskotu görsellerinin yüklenmesi."""
from PIL import Image, ImageOps

from src.ui.theme import ASSETS_DIR, BARN_OWL_SPRITE_PATH


def load_barn_owl_sprite(frame_idx: int = 0, facing_right: bool = False) -> Image.Image:
    """Kali-Owl siber-tribal tasarımlı ve 4 kare paytak yürüyüş (waddle) animasyonlu Peçeli Baykuş karesini yükler."""
    walk_frame_path = ASSETS_DIR / f"kali_owl_walk_{frame_idx % 4}.png"
    if walk_frame_path.exists():
        img = Image.open(walk_frame_path).convert("RGBA")
    elif BARN_OWL_SPRITE_PATH.exists():
        img = Image.open(BARN_OWL_SPRITE_PATH).convert("RGBA")
    else:
        img = Image.new("RGBA", (78, 76), (0, 0, 0, 0))
    if facing_right:
        img = ImageOps.mirror(img)
    return img
