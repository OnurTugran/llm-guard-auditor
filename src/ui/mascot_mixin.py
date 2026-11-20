"""Bilge Baykuş maskotu ve konuşma balonunun çizimi/animasyonu."""
from PIL import Image
from PIL import ImageTk
from src.ui.sprites import load_barn_owl_sprite
from src.ui.theme import KALI_OWL_LOGO_PATH
from src.ui.theme import THEME


class MascotMixin:
    def _animate_mascot(self) -> None:
        # Pencere simge durumuna küçültülmüşse CPU yormamak için çizimi atla
        if self.state() != "iconic":
            self.mascot_tick += 1
            self.mascot_x += self.mascot_dir * 3
            if self.mascot_x > 145:
                self.mascot_dir = -1
            elif self.mascot_x < 35:
                self.mascot_dir = 1
            self._draw_mascot_scene()
        self.after(150, self._animate_mascot)

    def _draw_mascot_scene(self) -> None:
        if not hasattr(self, "mascot_canvas") or not self.mascot_canvas.winfo_exists():
            return
        c = self.mascot_canvas
        c.delete("all")
        w = max(420, c.winfo_width())
        h = max(235, c.winfo_height())

        floor_y = h - 10
        c.create_line(10, floor_y, w - 10, floor_y, fill=THEME["border"], width=2)

        bx1, by1, bx2, by2 = 12, 8, w - 12, floor_y - 78
        if self.mascot_mood == "alert":
            border_col = THEME["fail"]
            fill_col = "#2D1622"
            title_col = "#FCA5A5"
        elif self.mascot_mood == "happy":
            border_col = THEME["pass"]
            fill_col = "#162A26"
            title_col = "#6EE7B7"
        else:
            border_col = THEME["accent"]
            fill_col = THEME["bg_card"]
            title_col = THEME["text_main"]

        c.create_rectangle(bx1, by1, bx2, by2, fill=fill_col, outline=border_col, width=2)

        tail_x = max(bx1 + 24, min(bx2 - 24, self.mascot_x + 44))
        c.create_polygon(
            tail_x - 8,
            by2,
            tail_x + 8,
            by2,
            tail_x,
            by2 + 12,
            fill=fill_col,
            outline=border_col,
            width=2,
        )

        sc = self.font_scale
        text_w = bx2 - bx1 - 70
        title_id = c.create_text(
            bx1 + 12, by1 + 8, anchor="nw", width=text_w, text=self.bubble_title,
            fill=title_col, font=("Segoe UI", max(9, int(12 * sc)), "bold"),
        )
        tb = c.bbox(title_id)
        body_y = (tb[3] + 6) if tb else by1 + 32
        body_id = c.create_text(
            bx1 + 12, body_y, anchor="nw", width=text_w, text=self.bubble_text,
            fill=THEME["text_main"], font=("Segoe UI", max(9, int(12 * sc))),
        )
        # Balona sığmayan uzun metni kısalt; tamamı için tıklama ipucu ekle
        shown = self.bubble_text
        truncated = False
        for _ in range(18):
            bb = c.bbox(body_id)
            if not bb or bb[3] <= by2 - 18 or len(shown) <= 30:
                break
            shown = shown[: int(len(shown) * 0.85)].rstrip()
            truncated = True
            c.itemconfigure(body_id, text=shown + " …")
        c.create_text(
            bx2 - 10, by2 - 6, anchor="se",
            text="🔍 tamamı için tıkla" if truncated else "🔍 tıkla: ayrıntı",
            fill=THEME["warn"] if truncated else THEME["text_dim"],
            font=("Segoe UI", 9, "bold" if truncated else "normal"),
        )

        # Konuşma bulutu sağ üst köşesinde Masaüstü Kali-Owl Siber Arması
        if self._kali_crest_photo is None and KALI_OWL_LOGO_PATH.exists():
            crest_img = Image.open(KALI_OWL_LOGO_PATH).convert("RGBA").resize((42, 42), Image.Resampling.LANCZOS)
            self._kali_crest_photo = ImageTk.PhotoImage(crest_img)
        if self._kali_crest_photo is not None:
            c.create_image(bx2 - 26, by1 + 28, image=self._kali_crest_photo, anchor="center")

        # --- ALTTA PAYTAK PAYTAK YÜRÜYEN KALI-TASARIMLI PEÇELİ BAYKUŞ (BARN OWL) ---
        facing_right = self.mascot_dir == 1
        f_idx = self.mascot_tick % 4
        cache_key = (f_idx, facing_right)
        if cache_key not in self._owl_sprite_cache:
            pil_img = load_barn_owl_sprite(frame_idx=f_idx, facing_right=facing_right)
            self._owl_sprite_cache[cache_key] = ImageTk.PhotoImage(pil_img)

        owl_photo = self._owl_sprite_cache[cache_key]
        c.create_oval(
            self.mascot_x + 18,
            floor_y - 6,
            self.mascot_x + 68,
            floor_y + 2,
            fill="#0E0B12",
            outline="",
        )
        c.create_image(self.mascot_x + 44, floor_y - 36, image=owl_photo, anchor="center")

        emote_x = self.mascot_x + 90
        emote_y = floor_y - 24
        if self.mascot_mood == "alert":
            c.create_text(
                emote_x,
                emote_y,
                anchor="w",
                text="🦉 ! ! [KANIT: İHLAL VEYA AĞ UYARISI]",
                fill=THEME["fail"],
                font=("Consolas", 9, "bold"),
            )
        elif self.mascot_mood == "happy":
            c.create_text(
                emote_x,
                emote_y,
                anchor="w",
                text="🦉 ✦ [İNCELEME SONUCU: TEMİZ / GÜVENLİ]",
                fill=THEME["pass"],
                font=("Consolas", 9, "bold"),
            )
        else:
            idle_tag = (
                "🦉 ~ kanıtları inceliyor..."
                if (self.mascot_tick % 8 < 4)
                else "🦉 ~ sessizce nöbette..."
            )
            c.create_text(
                emote_x,
                emote_y,
                anchor="w",
                text=idle_tag,
                fill=THEME["secondary"],
                font=("Consolas", 9),
            )
