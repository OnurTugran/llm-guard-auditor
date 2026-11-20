import ctypes
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk

ROOT_DIR = Path(__file__).parent
ICON_PATH = ROOT_DIR / "app_icon.ico"
PORTRAIT_PATH = ROOT_DIR / "assets" / "guardian_portrait.png"


def _load_default_probe_count() -> int:
    """Birleşik ana veri setindeki gerçek senaryo sayısını okur; okunamazsa 0 döner."""
    try:
        from src.dataset_hub import load_suite_by_filename

        return len(load_suite_by_filename("all_combined_master.json"))
    except Exception:
        return 0


PROBE_COUNT = _load_default_probe_count()

# Windows Görev Çubuğunda (Taskbar) kendi simgemizin görünmesi için AppUserModelID kaydı
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OWASP.LLMGuardAuditor.CRT.2.6")
except Exception:
    pass

# Kullanıcının Seçtiği Özel Renk Paleti
PALETTE = {
    "pale_sky": "#C9E0EB",        # Parlak metin ve vurgu
    "dusty_denim": "#7392B5",     # İkincil çerçeve ve alt metin
    "deep_lilac": "#8350C4",      # Ana neon mor çerçeve ve vurgu
    "midnight_violet": "#402B47", # İç panel dolgusu
    "shadow_grey": "#262423",     # Ana arka plan
    "scanline": "#211F1E",        # Çok hafifletilmiş CRT tarama çizgisi tonu
    "dim_violet": "#5A387E",      # Flicker (titreme) ara tonu
    "dark_core": "#1B1521",       # Portre ve alt HUD derin arka planı
}

# 16-Bit Klasik Sonic the Hedgehog Piksel Renk Tablosu
SONIC_PALETTE = {
    "D": (29, 53, 135, 255),    # Koyu mavi gölge/kontur
    "B": (46, 107, 230, 255),   # Klasik Sonic Mavisi
    "H": (120, 175, 255, 255),  # Parlak mavi diken vurgusu
    "S": (244, 194, 140, 255),  # Ten rengi (ağız, göbek, kulak içi)
    "W": (255, 255, 255, 255),  # Beyaz eldiven, göz ve ayakkabı şeridi
    "G": (16, 185, 129, 255),   # Yeşil göz bebeği
    "K": (17, 17, 24, 255),     # Siyah burun ve göz içi
    "R": (239, 68, 68, 255),    # Kırmızı Sonic ayakkabısı
    "P": (248, 113, 113, 255),  # Kırmızı koşu izi (Super Peel-Out efekti)
}

# 24x21 Piksel 4 Kare Sonic Koşu Animasyonu (Dikenler, Kulak, Yeşil Göz, Siyah Burun, Beyaz Eldiven, Kırmızı-Beyaz Ayakkabı)
SONIC_SPRITE_MATRICES = [
    # Kare 1: Adım Açık
    [
        "...........DDD..........",
        "......DDDDDBSDDD........",
        "...DDDBBBBBBBHHBDD......",
        ".DDBBBBBBBBBBBBBWWD.....",
        "DDBBBBBBBBBBBBBWWWWD....",
        "DDDDDBBBBBBBBBBWWGWD....",
        "....DDBBBBBBBBBWWKWD....",
        "..DDBBBBBBBBBBBWWWWD....",
        ".DDBBBBBBBBBBBBSSSSKK...",
        "DDBBBBBBBBBBBBSSSSSSK...",
        "DDDDDDDDDBBBBBSSSSSD....",
        ".....DDDBBBBBBBDDDD.....",
        "...DDBBBBBBBSSSBBD......",
        "..DDDDBBBBBSSSSBBD......",
        "....WWDBBBBSSSSBD.......",
        "...WWWWDBBBBBBBDD.......",
        "...WW..DDDDDDDDD.WW.....",
        "......RRRRW..DDRRWWW....",
        ".....RRRRWW...RRRRWW....",
        "....RRRRWWW....RRRR.....",
        "....DDDDDD.....DDDD.....",
    ],
    # Kare 2: Hızlanma (Orta Adım)
    [
        "...........DDD..........",
        ".....DDDDDDBSDDD........",
        "..DDDBBBBBBBBHHBDD......",
        ".DDBBBBBBBBBBBBBWWD.....",
        "DDBBBBBBBBBBBBBWWWWD....",
        "DDDDDBBBBBBBBBBWWGWD....",
        "...DDBBBBBBBBBBWWKWD....",
        ".DDBBBBBBBBBBBBWWWWD....",
        "DDBBBBBBBBBBBBBSSSSKK...",
        "DDDDDDDDDBBBBBSSSSSSK...",
        "....DDDBBBBBBBSSSSSD....",
        "...DDBBBBBBBBBBDDDD.....",
        "..DDDDBBBBBBSSSBBD......",
        ".....DDBBBBSSSSBBD......",
        "......DBBBBSSSSWW.......",
        "......DDBBBBBBBWWW......",
        ".......DDDDDDDD.WW......",
        "........RRRRW.RRRRW.....",
        ".......RRRRWW.RRRRWW....",
        ".......RRRRWW..RRRR.....",
        ".......DDDDD...DDDD.....",
    ],
    # Kare 3: Ters Adım
    [
        "...........DDD..........",
        "......DDDDDBSDDD........",
        "...DDDBBBBBBBHHBDD......",
        ".DDBBBBBBBBBBBBBWWD.....",
        "DDBBBBBBBBBBBBBWWWWD....",
        "DDDDDBBBBBBBBBBWWGWD....",
        "....DDBBBBBBBBBWWKWD....",
        "..DDBBBBBBBBBBBWWWWD....",
        ".DDBBBBBBBBBBBBSSSSKK...",
        "DDBBBBBBBBBBBBSSSSSSK...",
        "DDDDDDDDDBBBBBSSSSSD....",
        ".....DDDBBBBBBBDDDD.....",
        "...DDBBBBBBBSSSBBD......",
        "..DDDDBBBBBSSSSBBD.WW...",
        "......DBBBBSSSSBD.WWW...",
        ".....WWDBBBBBBBDD..WW...",
        "....WWWDDDDDDDDD........",
        ".....DDRRWW..RRRRW......",
        "......RRRRWW.RRRRWW.....",
        "......RRRR...RRRRWWW....",
        "......DDDD...DDDDDD.....",
    ],
    # Kare 4: Sonic Peel-Out Hız Tekerleği
    [
        "...........DDD..........",
        ".....DDDDDDBSDDD........",
        "..DDDBBBBBBBBHHBDD......",
        ".DDBBBBBBBBBBBBBWWD.....",
        "DDBBBBBBBBBBBBBWWWWD....",
        "DDDDDBBBBBBBBBBWWGWD....",
        "...DDBBBBBBBBBBWWKWD....",
        ".DDBBBBBBBBBBBBWWWWD....",
        "DDBBBBBBBBBBBBBSSSSKK...",
        "DDDDDDDDDBBBBBSSSSSSK...",
        "....DDDBBBBBBBSSSSSD....",
        "...DDBBBBBBBBBBDDDD.....",
        "..DDDDBBBBBBSSSBBD......",
        ".....WWBBBBSSSSBBD......",
        "....WWWDBBBSSSSBD.WW....",
        ".....WW.BBBBBBBDD.WWW...",
        ".......DDDDDDDDD..WW....",
        "......PRRRRWWRRRRP......",
        ".....PPRRRRWWWRRRPP.....",
        "......PRRRRWWRRRRP......",
        ".......PPPPPPPPPP.......",
    ],
]


def _build_sonic_pil_frames() -> list[Image.Image]:
    """4 karelik Sonic piksel matrisini şeffaf PIL görsellerine dönüştürür."""
    frames: list[Image.Image] = []
    for mat in SONIC_SPRITE_MATRICES:
        h = len(mat)
        w = len(mat[0])
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        px = img.load()
        for r, row in enumerate(mat):
            for c, ch in enumerate(row):
                if ch in SONIC_PALETTE:
                    px[c, r] = SONIC_PALETTE[ch]
        frames.append(img)
    return frames


def _load_real_code_lines() -> list[str]:
    """Proje dosyalarındaki gerçek Python kod komutlarını okur ve CRT ekranında akıtmak üzere hazırlar."""
    snippets: list[str] = []
    target_files = [
        ROOT_DIR / "src" / "engine.py",
        ROOT_DIR / "src" / "evaluators.py",
        ROOT_DIR / "src" / "target_client.py",
    ]
    for fp in target_files:
        if fp.exists():
            try:
                for raw_line in fp.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if line and not line.startswith("#") and not line.startswith('"""'):
                        snippets.append(f"{fp.name}> {line[:44]}")
            except Exception:
                pass
    if not snippets:
        snippets = [
            "engine.py> async with semaphore:",
            "engine.py> reply, ms = await query_target(prompt)",
            "evaluators.py> res = await litellm.acompletion(...)",
            "evaluators.py> return JudgeVerdict(outcome=\"passed\")",
            "target_client.py> response = await client.post(url)",
        ]
    return snippets


class RetroCRTLauncher(tk.Tk):
    BASE_W = 760
    BASE_H = 540

    def __init__(self) -> None:
        super().__init__()
        self.title("OWASP // LLM Guard Auditor")
        self.attributes("-alpha", 0.0)
        self.geometry("1x1+0+0")

        if ICON_PATH.exists():
            try:
                self.iconbitmap(default=str(ICON_PATH))
            except Exception:
                pass

        # Asıl Çerçevesiz CRT Penceresi (Toplevel)
        self.crt_win = tk.Toplevel(self)
        self.crt_win.title("OWASP // LLM Guard Auditor")
        self.crt_win.configure(bg=PALETTE["shadow_grey"])
        self.crt_win.overrideredirect(True)

        self.is_maximized = False
        self.scale_factor = 1.0
        self._center_window(self.BASE_W, self.BASE_H)

        # Pencere sürükleme değişkenleri
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._is_dragging = False

        # Durum ve Animasyon değişkenleri
        self.selected_idx = 0
        self.hovered_win_btn: int | None = None
        self.scan_offset = 0
        self.cursor_visible = True
        self.code_pool = _load_real_code_lines()
        self.code_scroll_idx = 0
        self.flicker_tick = 0
        self.eq_heights = [12, 24, 18, 30, 14, 26, 20, 16]

        # 2D Sonic Koşu Sahnesi değişkenleri
        self._raw_sonic_frames = _build_sonic_pil_frames()
        self._tk_sonic_frames: list[ImageTk.PhotoImage] = []
        self._cached_sonic_scale: float = 0.0
        self.runner_x = 355
        self.runner_frame_idx = 0
        self.runner_score = 0
        self.rings_x = [440, 515, 590, 665]
        self.sparkle_effects: list[tuple[int, int]] = []  # (x, kalan_tick)

        # Sol karakter portresini yükle
        self._raw_portrait: Image.Image | None = None
        self._tk_portrait: ImageTk.PhotoImage | None = None
        self._cached_portrait_scale: float = 0.0
        if PORTRAIT_PATH.exists():
            try:
                self._raw_portrait = Image.open(PORTRAIT_PATH)
            except Exception:
                pass

        self.status_message = (
            f"SISTEM HAZIR // {PROBE_COUNT} OWASP, GARAK, PYRIT VE HF TEST SENARYOSU BELLEKTE. "
            "BASLATMAK ICIN BIR MOD SECIN..."
        )
        self.typed_len = 0

        self.canvas = tk.Canvas(
            self.crt_win,
            width=self.BASE_W,
            height=self.BASE_H,
            bg=PALETTE["shadow_grey"],
            highlightthickness=0,
            bd=0,
            cursor="arrow",
        )
        self.canvas.pack(fill="both", expand=True)

        self.menu_items = [
            {
                "label": "[1] MASAUSTU UYGULAMASI (NATIVE APP)",
                "desc": "KARANLIK TEMALI WINDOWS DENETIM EKRANINI ACAR.",
                "action": self._launch_desktop,
            },
            {
                "label": "[2] WEB ARAYUZU (BROWSER TERMINAL)",
                "desc": "TARAYICI UZERINDE INTERAKTIF PANELI BASLATIR.",
                "action": self._launch_web,
            },
        ]

        # Klavye kontrolleri
        for w in (self, self.crt_win):
            w.bind("<Up>", self._on_key_up)
            w.bind("<Down>", self._on_key_down)
            w.bind("<Return>", self._on_key_enter)
            w.bind("<Escape>", lambda _e: self.destroy())
            w.bind("1", lambda _e: self._launch_desktop())
            w.bind("2", lambda _e: self._launch_web())

        # Görev çubuğundan küçültme / geri açma senkronizasyonu
        self.bind("<Unmap>", self._on_root_unmap)
        self.bind("<Map>", self._on_root_map)
        self.bind("<FocusIn>", self._on_root_focus)

        # Fare kontrolleri
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_press)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)

        self.crt_win.lift()
        self.crt_win.focus_force()

        self._render_frame()
        self._animate_loop()

    def _on_root_unmap(self, _event: object) -> None:
        if self.crt_win.winfo_exists():
            self.crt_win.withdraw()

    def _on_root_map(self, _event: object) -> None:
        if self.crt_win.winfo_exists():
            self.crt_win.deiconify()
            self.crt_win.lift()
            self.crt_win.focus_force()

    def _on_root_focus(self, _event: object) -> None:
        if self.crt_win.winfo_exists() and self.state() == "normal":
            self.crt_win.deiconify()
            self.crt_win.lift()

    def _center_window(self, w: int, h: int) -> None:
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.crt_win.geometry(f"{w}x{h}+{x}+{y}")

    def _get_scaled_portrait(self) -> ImageTk.PhotoImage | None:
        if self._raw_portrait is None:
            return None
        if self._tk_portrait is None or abs(self._cached_portrait_scale - self.scale_factor) > 0.01:
            pw = max(1, int(268 * self.scale_factor))
            ph = max(1, int(272 * self.scale_factor))
            resized = self._raw_portrait.resize((pw, ph), Image.Resampling.LANCZOS)
            self._tk_portrait = ImageTk.PhotoImage(resized)
            self._cached_portrait_scale = self.scale_factor
        return self._tk_portrait

    def _get_scaled_sonic_frame(self, idx: int) -> ImageTk.PhotoImage:
        if not self._tk_sonic_frames or abs(self._cached_sonic_scale - self.scale_factor) > 0.01:
            # 24x21 pikseli 2 kat (48x42) piksel keskinliğinde (NEAREST) büyüt
            sw = max(1, int(46 * self.scale_factor))
            sh = max(1, int(40 * self.scale_factor))
            self._tk_sonic_frames = [
                ImageTk.PhotoImage(im.resize((sw, sh), Image.Resampling.NEAREST))
                for im in self._raw_sonic_frames
            ]
            self._cached_sonic_scale = self.scale_factor
        return self._tk_sonic_frames[idx % len(self._tk_sonic_frames)]

    def _draw_pixel_rect(
        self, x1: int, y1: int, x2: int, y2: int, fill: str, outline: str, thickness: int = 3
    ) -> None:
        self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=thickness)
        c = 4
        for cx, cy in [(x1, y1), (x2 - c, y1), (x1, y2 - c), (x2 - c, y2 - c)]:
            self.canvas.create_rectangle(cx, cy, cx + c, cy + c, fill=PALETTE["pale_sky"], outline="")

    def _draw_2d_runner_stage(self) -> None:
        """Green Hill tarzı zemin, altın halkalar ve 16-bit Sonic koşu sahnesi."""
        sx1, sy1, sx2, sy2 = 338, 342, 722, 404
        self.canvas.create_rectangle(
            sx1, sy1, sx2, sy2, fill=PALETTE["dark_core"], outline=PALETTE["deep_lilac"], width=2
        )

        # Arka plan yıldızları
        for star_i in range(7):
            st_x = sx1 + 15 + ((star_i * 55 - self.flicker_tick * 4) % (sx2 - sx1 - 30))
            st_y = sy1 + 10 + (star_i % 2) * 10
            self.canvas.create_rectangle(st_x, st_y, st_x + 2, st_y + 2, fill=PALETTE["dim_violet"], outline="")

        # Green Hill tarzı dama taşlı zemin
        ground_y = sy2 - 12
        self.canvas.create_line(sx1 + 2, ground_y, sx2 - 2, ground_y, fill="#38bdf8", width=2)
        tile_offset = (self.flicker_tick * 8) % 16
        for tx in range(sx1 + 4, sx2 - 12, 16):
            draw_x = tx - tile_offset
            if sx1 + 4 <= draw_x <= sx2 - 12:
                self.canvas.create_rectangle(
                    draw_x, ground_y + 2, draw_x + 8, sy2 - 3, fill=PALETTE["midnight_violet"], outline=""
                )

        # Altın Sonic Halkaları (Golden Rings) - dönme animasyonlu
        ring_w = 5 if (self.flicker_tick % 3 != 0) else 2
        for rx in self.rings_x:
            if sx1 + 20 < rx < sx2 - 20:
                ry = ground_y - 16
                self.canvas.create_oval(
                    rx - ring_w, ry - 6, rx + ring_w, ry + 6, outline="#facc15", width=2
                )

        # Halka toplama parıltı efektleri (✦)
        for sp_x, _ttl in self.sparkle_effects:
            self.canvas.create_text(
                sp_x, ground_y - 20, text="✦", fill="#fef08a", font=("Consolas", 10, "bold")
            )

        # Sonic'in arkasındaki mavi süpersonik hız çizgileri
        for trail_i in range(1, 4):
            tx = self.runner_x - 16 - trail_i * 9
            if tx > sx1 + 6:
                ty = ground_y - 18 + (trail_i % 2) * 5
                self.canvas.create_line(tx, ty, tx + 7, ty, fill="#3b82f6", width=2)

        # Sağ üstte mini Sonic Ring sayacı
        self.canvas.create_text(
            sx2 - 10,
            sy1 + 3,
            anchor="ne",
            text=f"RINGS {self.runner_score:03d}",
            fill="#facc15",
            font=("Consolas", 8, "bold"),
        )

    def _render_frame(self) -> None:
        self.canvas.delete("all")

        # 1. Dış CRT Çerçevesi
        self._draw_pixel_rect(
            10, 10, 750, 530, fill=PALETTE["shadow_grey"], outline=PALETTE["deep_lilac"], thickness=4
        )

        # 2. Üst Başlık Çubuğu
        self.canvas.create_rectangle(
            20, 20, 740, 54, fill=PALETTE["midnight_violet"], outline=PALETTE["deep_lilac"], width=2
        )
        title_col = PALETTE["pale_sky"] if (self.flicker_tick % 11 != 0) else PALETTE["dusty_denim"]
        self.canvas.create_text(
            34,
            37,
            anchor="w",
            text="✦ OWASP // LLM_GUARD_AUDITOR v2.6",
            fill=title_col,
            font=("Consolas", 13, "bold"),
        )

        # Sağ üstteki aktif çalışan [_] [□] [X] pencere kontrol tuşları
        self.win_btn_bboxes = []
        symbols = ["_", "□", "X"]
        for i, sym in enumerate(symbols):
            bx = 666 + i * 24
            by = 27
            bw, bh = 20, 20
            self.win_btn_bboxes.append((bx, by, bx + bw, by + bh))

            is_hov = self.hovered_win_btn == i
            if is_hov:
                btn_fill = "#b91c1c" if i == 2 else PALETTE["deep_lilac"]
                btn_outline = PALETTE["pale_sky"]
                txt_col = PALETTE["pale_sky"]
            else:
                btn_fill = PALETTE["shadow_grey"]
                btn_outline = PALETTE["dusty_denim"]
                txt_col = PALETTE["pale_sky"]

            self.canvas.create_rectangle(
                bx, by, bx + bw, by + bh, fill=btn_fill, outline=btn_outline, width=2
            )
            if sym == "_":  # küçült simgesi: yazı karakteri yerine net bir çizgi
                self.canvas.create_line(bx + 5, by + 14, bx + 15, by + 14, fill=txt_col, width=2)
            else:
                self.canvas.create_text(
                    bx + 10, by + 10, text=sym, fill=txt_col, font=("Consolas", 9, "bold")
                )

        # 3. SOL PANEL: Karakter Portresi
        self._draw_pixel_rect(
            24, 66, 310, 412, fill=PALETTE["dark_core"], outline=PALETTE["deep_lilac"], thickness=3
        )
        self.canvas.create_rectangle(30, 72, 304, 96, fill=PALETTE["deep_lilac"], outline="")
        self.canvas.create_text(
            40,
            84,
            anchor="w",
            text="GUARD_CORE // SENTINEL_01",
            fill=PALETTE["shadow_grey"],
            font=("Consolas", 10, "bold"),
        )

        self.canvas.create_rectangle(
            32, 100, 302, 374, fill=PALETTE["dark_core"], outline=PALETTE["midnight_violet"], width=1
        )

        self.canvas.create_text(
            167,
            392,
            text="♥ ♥ ♥ ♥ ♥   [SHIELD: ACTIVE]",
            fill=PALETTE["pale_sky"],
            font=("Consolas", 10, "bold"),
        )

        # 4. SAĞ ÜST PANEL: FLICKERING CANLI KOD KOMUTLARI
        code_box_outline = (
            PALETTE["pale_sky"] if (self.flicker_tick % 14 == 0) else PALETTE["deep_lilac"]
        )
        self._draw_pixel_rect(
            324, 66, 736, 198, fill=PALETTE["midnight_violet"], outline=code_box_outline, thickness=3
        )

        hdr_flicker = (
            "⚡ MEM_STREAM // LIVE_SOURCE"
            if (self.flicker_tick % 7 != 0)
            else "⚡ SYNC_BUFFER // 0x8350C4"
        )
        self.canvas.create_text(
            338,
            76,
            anchor="nw",
            text=hdr_flicker,
            fill=PALETTE["pale_sky"] if (self.flicker_tick % 4 == 0) else PALETTE["dusty_denim"],
            font=("Consolas", 9, "bold"),
        )

        visible_count = 5
        for line_offset in range(visible_count):
            idx = (self.code_scroll_idx + line_offset) % len(self.code_pool)
            code_line = self.code_pool[idx]

            r_val = (self.flicker_tick + line_offset * 3) % 10
            if line_offset == visible_count - 1:
                line_color = PALETTE["pale_sky"] if r_val != 0 else PALETTE["dusty_denim"]
                prefix_sym = ">> "
            elif r_val in (0, 5):
                line_color = PALETTE["dim_violet"]
                prefix_sym = "   "
            elif r_val == 2:
                line_color = PALETTE["deep_lilac"]
                prefix_sym = " * "
            else:
                line_color = PALETTE["dusty_denim"]
                prefix_sym = "   "

            full_line = prefix_sym + code_line
            if len(full_line) > 50:
                full_line = full_line[:49].rstrip() + "…"
            self.canvas.create_text(
                336,
                96 + line_offset * 18,
                anchor="nw",
                text=full_line,
                fill=line_color,
                font=("Consolas", 9, "bold"),
            )

        # 5. SAĞ ORTA PANEL: 2 Seçenek + Sonic Koşu Sahnesi
        self._draw_pixel_rect(
            324, 208, 736, 412, fill=PALETTE["shadow_grey"], outline=PALETTE["dusty_denim"], thickness=3
        )
        self.canvas.create_text(
            340,
            218,
            anchor="nw",
            text="SELECT EXECUTION MODE (KLAVYE ▲/▼ VEYA FARE):",
            fill=PALETTE["dusty_denim"],
            font=("Consolas", 9, "bold"),
        )

        self.button_bboxes = []
        for idx, item in enumerate(self.menu_items):
            by1 = 240 + idx * 50
            by2 = by1 + 42
            bx1, bx2 = 338, 722
            self.button_bboxes.append((bx1, by1, bx2, by2))

            is_sel = idx == self.selected_idx
            bg_col = PALETTE["deep_lilac"] if is_sel else PALETTE["midnight_violet"]
            fg_col = PALETTE["pale_sky"] if is_sel else PALETTE["dusty_denim"]
            border_col = PALETTE["pale_sky"] if is_sel else PALETTE["deep_lilac"]
            prefix = "▶ " if is_sel else "  "

            self.canvas.create_rectangle(
                bx1, by1, bx2, by2, fill=bg_col, outline=border_col, width=2
            )
            main_label, _, tag = item["label"].partition(" (")
            self.canvas.create_text(
                bx1 + 14,
                by1 + 21,
                anchor="w",
                text=prefix + main_label,
                fill=fg_col,
                font=("Consolas", 11, "bold"),
            )
            if tag:
                self.canvas.create_text(
                    bx2 - 12,
                    by1 + 21,
                    anchor="e",
                    text=tag.rstrip(")"),
                    fill=PALETTE["pale_sky"] if is_sel else PALETTE["dusty_denim"],
                    font=("Consolas", 8, "bold"),
                )

        # Sonic Sahne Zemini ve Halkalar
        self._draw_2d_runner_stage()

        # 6. ALT PANEL: CYBER-HUD TELEMETRY & COMMAND DECK
        self._draw_pixel_rect(
            24, 422, 736, 516, fill=PALETTE["dark_core"], outline=PALETTE["deep_lilac"], thickness=3
        )
        self.canvas.create_rectangle(
            28, 426, 732, 446, fill=PALETTE["midnight_violet"], outline=""
        )
        self.canvas.create_text(
            38,
            436,
            anchor="w",
            text="⚡ SYS_TELEMETRY // COMMAND_DECK",
            fill=PALETTE["dusty_denim"],
            font=("Consolas", 9, "bold"),
        )
        self.canvas.create_text(
            724,
            436,
            anchor="e",
            text=f"[PROBES: {PROBE_COUNT}]  [ENGINE: ASYNC_IO]  [ONLINE]",
            fill=PALETTE["dusty_denim"],
            font=("Consolas", 8, "bold"),
        )

        # Sol HUD Bölümü: Spektrum Barları
        self.canvas.create_rectangle(
            34, 452, 134, 508, fill=PALETTE["shadow_grey"], outline=PALETTE["midnight_violet"], width=2
        )
        for b_idx, bh in enumerate(self.eq_heights):
            bx = 42 + b_idx * 11
            by_bottom = 502
            by_top = by_bottom - bh
            bar_col = (
                PALETTE["pale_sky"]
                if bh > 24
                else (PALETTE["deep_lilac"] if bh > 16 else PALETTE["dusty_denim"])
            )
            self.canvas.create_rectangle(bx, by_top, bx + 7, by_bottom, fill=bar_col, outline="")

        # Orta HUD Bölümü: Komut & Durum Konsolu
        shown_txt = self.status_message[: self.typed_len]
        if self.cursor_visible:
            shown_txt += " █"
        self.canvas.create_text(
            148,
            456,
            anchor="nw",
            width=410,
            text=">> " + shown_txt,
            fill=PALETTE["pale_sky"],
            font=("Consolas", 10, "bold"),
        )

        # Sağ HUD Bölümü: Kalkan Bütünlüğü & Enerji Modülü
        self.canvas.create_line(572, 452, 572, 508, fill=PALETTE["midnight_violet"], width=2)
        self.canvas.create_text(
            584,
            456,
            anchor="nw",
            text="SHIELD // 100%",
            fill=PALETTE["dusty_denim"],
            font=("Consolas", 8, "bold"),
        )
        for seg in range(8):
            sx = 584 + seg * 17
            seg_col = PALETTE["pale_sky"] if seg == (self.flicker_tick % 8) else PALETTE["deep_lilac"]
            self.canvas.create_rectangle(sx, 474, sx + 12, 488, fill=seg_col, outline="")

        self.canvas.create_text(
            584,
            494,
            anchor="nw",
            text=f"ADDR 0x{402000 + (self.flicker_tick * 16) % 8999:06X}",
            fill=PALETTE["dusty_denim"],
            font=("Consolas", 8),
        )

        # 7. HAFİFLETİLMİŞ TÜPLÜ TELEVİZYON EFEKTİ
        for y in range(18 + (self.scan_offset % 10), 524, 10):
            self.canvas.create_line(16, y, 744, y, fill=PALETTE["scanline"], width=1, stipple="gray25")

        if self.scale_factor != 1.0:
            self.canvas.scale("all", 0, 0, self.scale_factor, self.scale_factor)

        # Sol Karakter Portresi
        tk_img = self._get_scaled_portrait()
        if tk_img is not None:
            self.canvas.create_image(
                int(167 * self.scale_factor),
                int(237 * self.scale_factor),
                image=tk_img,
                anchor="center",
            )

        # 16-Bit Sonic Sprite Çizimi
        sonic_img = self._get_scaled_sonic_frame(self.runner_frame_idx)
        bob_y = -1 if (self.flicker_tick % 2 == 0) else 0
        self.canvas.create_image(
            int(self.runner_x * self.scale_factor),
            int((373 + bob_y) * self.scale_factor),
            image=sonic_img,
            anchor="center",
        )

    def _animate_loop(self) -> None:
        if not self._is_dragging:
            self.scan_offset = (self.scan_offset + 1) % 10
            self.flicker_tick += 1

            # 16-Bit Sonic Koşu Animasyonu
            self.runner_frame_idx = (self.runner_frame_idx + 1) % len(self._raw_sonic_frames)
            self.runner_x += 10
            if self.runner_x > 696:
                self.runner_x = 362
                self.rings_x = [440, 515, 590, 665]

            # Parıltı efektlerinin süresini azalt
            self.sparkle_effects = [(x, ttl - 1) for x, ttl in self.sparkle_effects if ttl > 1]

            # Sonic halkalara değince altın parıltıyla topla
            remaining_rings = []
            for rx in self.rings_x:
                if abs(self.runner_x - rx) < 16:
                    self.runner_score += 1
                    self.sparkle_effects.append((rx, 4))
                else:
                    remaining_rings.append(rx)
            self.rings_x = remaining_rings

            # Spektrum barlarını yumuşakça hareket ettir
            for i in range(len(self.eq_heights)):
                delta = ((self.flicker_tick + i * 3) % 5) - 2
                self.eq_heights[i] = max(8, min(38, self.eq_heights[i] + delta * 3))

            if self.flicker_tick % 5 == 0:
                self.code_scroll_idx = (self.code_scroll_idx + 1) % len(self.code_pool)

            if self.typed_len < len(self.status_message):
                self.typed_len = min(len(self.status_message), self.typed_len + 3)
            elif self.flicker_tick % 4 == 0:
                self.cursor_visible = not self.cursor_visible

            self._render_frame()

        self.after(75, self._animate_loop)

    def _set_status(self, msg: str) -> None:
        self.status_message = msg
        self.typed_len = 0

    def _to_base_coords(self, ex: int, ey: int) -> tuple[float, float]:
        return ex / self.scale_factor, ey / self.scale_factor

    # --- PENCERE KONTROL İŞLEVLERİ: [_] [□] [X] ve SÜRÜKLEME ---
    def _minimize_window(self) -> None:
        self.crt_win.withdraw()
        self.iconify()

    def _toggle_maximize(self) -> None:
        self.is_maximized = not self.is_maximized
        if self.is_maximized:
            sh = self.winfo_screenheight()
            target_h = int(sh * 0.84)
            self.scale_factor = target_h / self.BASE_H
            target_w = int(self.BASE_W * self.scale_factor)
            self._center_window(target_w, target_h)
            self._set_status("EKRAN OLCEGI BUYUTULDU (MAXIMIZE MODE: ON).")
        else:
            self.scale_factor = 1.0
            self._center_window(self.BASE_W, self.BASE_H)
            self._set_status("STANDART CRT EKRAN BOYUTUNA DONULDU.")

    def _on_mouse_press(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        bx, by = self._to_base_coords(event.x, event.y)
        self._is_dragging = False

        for i, (x1, y1, x2, y2) in enumerate(self.win_btn_bboxes):
            if x1 <= bx <= x2 and y1 <= by <= y2:
                if i == 0:
                    self._minimize_window()
                elif i == 1:
                    self._toggle_maximize()
                elif i == 2:
                    self.destroy()
                return

        for idx, (x1, y1, x2, y2) in enumerate(self.button_bboxes):
            if x1 <= bx <= x2 and y1 <= by <= y2:
                self.selected_idx = idx
                self.menu_items[idx]["action"]()
                return

        if 0 <= by <= 62 or bx <= 24 or bx >= 736 or by >= 514:
            self._is_dragging = True
            self._drag_offset_x = self.winfo_pointerx() - self.crt_win.winfo_x()
            self._drag_offset_y = self.winfo_pointery() - self.crt_win.winfo_y()

    def _on_mouse_drag(self, _event: tk.Event) -> None:  # type: ignore[type-arg]
        if self._is_dragging:
            new_x = self.winfo_pointerx() - self._drag_offset_x
            new_y = self.winfo_pointery() - self._drag_offset_y
            self.crt_win.geometry(f"+{new_x}+{new_y}")

    def _on_mouse_release(self, _event: tk.Event) -> None:  # type: ignore[type-arg]
        self._is_dragging = False

    def _on_double_click(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        bx, by = self._to_base_coords(event.x, event.y)
        if 0 <= by <= 60 and bx < 660:
            self._toggle_maximize()

    def _on_mouse_move(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        if self._is_dragging:
            return
        bx, by = self._to_base_coords(event.x, event.y)

        hov_win = None
        for i, (x1, y1, x2, y2) in enumerate(self.win_btn_bboxes):
            if x1 <= bx <= x2 and y1 <= by <= y2:
                hov_win = i
                break
        self.hovered_win_btn = hov_win

        in_menu_btn = False
        for idx, (x1, y1, x2, y2) in enumerate(self.button_bboxes):
            if x1 <= bx <= x2 and y1 <= by <= y2:
                in_menu_btn = True
                if self.selected_idx != idx:
                    self.selected_idx = idx
                    self._set_status(self.menu_items[idx]["desc"])
                break

        if hov_win is not None or in_menu_btn:
            self.canvas.configure(cursor="hand2")
        else:
            self.canvas.configure(cursor="arrow")

    def _on_key_up(self, _event: object) -> None:
        self.selected_idx = (self.selected_idx - 1) % len(self.menu_items)
        self._set_status(self.menu_items[self.selected_idx]["desc"])

    def _on_key_down(self, _event: object) -> None:
        self.selected_idx = (self.selected_idx + 1) % len(self.menu_items)
        self._set_status(self.menu_items[self.selected_idx]["desc"])

    def _on_key_enter(self, _event: object) -> None:
        self.menu_items[self.selected_idx]["action"]()

    def _launch_desktop(self) -> None:
        self.destroy()
        from desktop_app import LLMGuardDesktopApp

        app = LLMGuardDesktopApp()
        app.mainloop()

    def _launch_web(self) -> None:
        self._set_status("WEB TERMINALI BASLATILIYOR... LUTFEN BEKLEYIN...")
        self.update_idletasks()
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT_DIR / "app.py"),
                "--browser.gatherUsageStats=false",
            ],
            cwd=str(ROOT_DIR),
        )
        self.destroy()


if __name__ == "__main__":
    launcher = RetroCRTLauncher()
    launcher.mainloop()
