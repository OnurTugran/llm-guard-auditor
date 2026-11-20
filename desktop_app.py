"""OWASP LLM Güvenlik Denetim Aracı: masaüstü arayüzü (CustomTkinter).

Arayüz bileşenleri src/ui/ altındaki mixin'lere bölünmüştür:
- ConfigMixin   : hedef/hakem ayarları, veri seti seçimi
- BridgeMixin   : tarayıcı köprüsü düğmeleri
- ResultsMixin  : sonuç tablosu, detay penceresi, elle karar, kayıt, rapor
- MascotMixin   : baykuş maskotu ve konuşma balonu
"""
import asyncio
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional
import customtkinter as ctk
from PIL import ImageTk

from src.dataset_hub import SUITE_CATALOG, load_suite_by_filename, without_pressure_suffix
from src.detail_window import ResultDetailWindow
from src.engine import run_test_suite
from src.models import EvaluationResult, TestCase
from src.ui.bridge_mixin import BridgeMixin
from src.ui.config_mixin import ConfigMixin
from src.ui.headers import parse_headers_or_cookie_input  # noqa: F401  (geriye dönük içe aktarma)
from src.ui.mascot_mixin import MascotMixin
from src.ui.results_mixin import ResultsMixin
from src.ui.sprites import load_barn_owl_sprite  # noqa: F401
from src.ui.theme import ICON_PATH, THEME, row_display as _row_display  # noqa: F401

ctk.set_appearance_mode("dark")


class LLMGuardDesktopApp(ConfigMixin, BridgeMixin, ResultsMixin, MascotMixin, ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=THEME["bg_main"])
        self.title("🛡️ OWASP LLM Güvenlik ve Uyumluluk Denetim Aracı")
        self.geometry("1260x800")
        self.minsize(1080, 700)
        if ICON_PATH.exists():
            try:
                self.iconbitmap(str(ICON_PATH))
            except Exception:
                pass

        self.test_cases: list[TestCase] = load_suite_by_filename("all_combined_master.json")
        self.eval_results: list[EvaluationResult] = []
        self.last_elapsed: float = 0.0
        self.active_cancel_event: Optional[asyncio.Event] = None
        self.current_filter: str = "all"
        self._key_visible: bool = False
        self.font_scale: float = 1.0
        self.selected_idx: Optional[int] = None
        self._detail_win: Optional[ResultDetailWindow] = None
        self._run_meta: tuple[str, str] = ("-", "-")
        self._autosave_path = Path(__file__).resolve().parent / "runs" / "son_denetim.jsonl"

        # Maskot (Kali-Owl Siber Tasarımlı Paytak Yürüyen Baykuş) ve Konuşma Bulutu durumu
        self.mascot_x = 65
        self.mascot_dir = 1
        self.mascot_tick = 0
        self.mascot_mood = "idle"  # "idle", "alert", "happy"
        self._owl_sprite_cache: dict[tuple[int, bool], ImageTk.PhotoImage] = {}
        self._kali_crest_photo: Optional[ImageTk.PhotoImage] = None
        self.bubble_title = "🦉 BİLGE BAYKUŞ // SİBER DENETÇİ NÖBETTE"
        self.bubble_text = (
            "Merhaba! Denetimi başlattıktan sonra tablodan bir satıra tıkla; hakemin açıklamasını "
            "burada anlatırım. Yazı küçük ya da uzun gelirse beni (konuşma bulutunu) tıkla, "
            "satıra çift tıkla veya 🔍 Detay düğmesine bas: soru, cevap ve gerekçe büyük pencerede açılır."
        )

        self._build_layout()
        self._animate_mascot()

    def _create_sidebar_card(self, parent: ctk.CTkScrollableFrame, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=THEME["bg_card"],
            corner_radius=10,
            border_width=1,
            border_color=THEME["border"],
        )
        card.pack(fill="x", padx=8, pady=(0, 10))
        ctk.CTkLabel(
            card,
            text=title,
            text_color=THEME["text_main"],
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(10, 6))
        return card

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ================= SOL PANEL (KOMPAKT SİBER KARTLAR) =================
        sidebar = ctk.CTkScrollableFrame(
            self,
            width=335,
            corner_radius=0,
            fg_color=THEME["bg_panel"],
            scrollbar_button_color=THEME["border"],
            scrollbar_button_hover_color=THEME["accent"],
        )
        sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        # Sol Üst Başlık Bandı
        brand_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand_frame.pack(fill="x", padx=10, pady=(10, 8))
        ctk.CTkLabel(
            brand_frame,
            text="🦉 CYBER-OWL AUDITOR",
            text_color=THEME["text_main"],
            font=ctk.CTkFont(family="Consolas", size=16, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_frame,
            text="OWASP LLM Top 10 Denetim Yapılandırması",
            text_color=THEME["text_dim"],
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w")

        # --- KART 1: HAKEM MODEL (JUDGE) ---
        card_judge = self._create_sidebar_card(sidebar, "⚖️ 1. Hakem Model (Judge)")

        self.judge_provider_var = ctk.StringVar(value="gemini")
        self.judge_provider_menu = ctk.CTkOptionMenu(
            card_judge,
            variable=self.judge_provider_var,
            values=["gemini", "anthropic", "openai", "xai", "groq", "rule_only"],
            fg_color=THEME["accent"],
            button_color=THEME["accent_hover"],
            button_hover_color=THEME["border"],
            text_color=THEME["text_main"],
            command=self._on_judge_provider_change,
        )
        self.judge_provider_menu.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            card_judge, text="Model Seçimi (veya Elle Yazın):", text_color=THEME["text_dim"], font=ctk.CTkFont(size=12)
        ).pack(anchor="w", padx=12)
        self.judge_model_entry = ctk.CTkComboBox(
            card_judge,
            fg_color=THEME["bg_input"],
            border_color=THEME["border"],
            button_color=THEME["border"],
            button_hover_color=THEME["accent"],
            text_color=THEME["text_main"],
            values=[
                "gemini/gemini-3.1-flash-lite",
                "gemini/gemini-2.5-flash",
                "gemini/gemini-3.8-flash",
                "gemini/gemini-3.5-flash",
                "gemini/gemini-2.5-pro",
                "gemini/gemini-2.5-flash-lite",
                "gemini/gemma-4-31b-it",
            ],
        )
        self.judge_model_entry.set("gemini/gemini-3.1-flash-lite")
        self.judge_model_entry.pack(fill="x", padx=12, pady=(2, 6))

        ctk.CTkLabel(
            card_judge, text="Hakem API Anahtarı:", text_color=THEME["text_dim"], font=ctk.CTkFont(size=12)
        ).pack(anchor="w", padx=12)

        key_row = ctk.CTkFrame(card_judge, fg_color="transparent")
        key_row.pack(fill="x", padx=12, pady=(2, 10))
        key_row.grid_columnconfigure(0, weight=1)

        self.judge_key_entry = ctk.CTkEntry(
            key_row,
            show="*",
            fg_color=THEME["bg_input"],
            border_color=THEME["border"],
            text_color=THEME["text_main"],
            placeholder_text="API Anahtarınızı girin...",
        )
        env_key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
        if env_key:
            self.judge_key_entry.insert(0, env_key)
        self.judge_key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.toggle_key_btn = ctk.CTkButton(
            key_row,
            text="👁️",
            width=34,
            fg_color=THEME["border"],
            hover_color=THEME["accent"],
            command=self._toggle_key_visibility,
        )
        self.toggle_key_btn.grid(row=0, column=1)

        # --- KART 2: HEDEF SİSTEM (TARGET) ---
        card_target = self._create_sidebar_card(sidebar, "🎯 2. Hedef Sistem (Target)")

        self.target_mode_var = ctk.StringVar(value="browser_bridge")
        self.target_mode_menu = ctk.CTkOptionMenu(
            card_target,
            variable=self.target_mode_var,
            values=["browser_bridge", "demo_sandbox", "openai_compatible", "custom_http"],
            fg_color=THEME["accent"],
            button_color=THEME["accent_hover"],
            button_hover_color=THEME["border"],
            text_color=THEME["text_main"],
            command=self._on_target_mode_change,
        )
        self.target_mode_menu.pack(fill="x", padx=12, pady=(0, 6))

        self.target_config_frame = ctk.CTkFrame(card_target, fg_color="transparent")
        self.target_config_frame.pack(fill="x", padx=8, pady=(0, 8))
        self._build_target_fields("browser_bridge")

        # --- KART 3: VERİ SETİ & PERFORMANS ---
        card_suite = self._create_sidebar_card(sidebar, "📚 3. Veri Seti & Hız Ayarları")

        self.suite_var = ctk.StringVar(value="all_combined_master.json")
        self.suite_menu = ctk.CTkOptionMenu(
            card_suite,
            variable=self.suite_var,
            values=list(SUITE_CATALOG.keys()),
            fg_color=THEME["border"],
            button_color=THEME["accent"],
            button_hover_color=THEME["accent_hover"],
            text_color=THEME["text_main"],
            command=self._on_suite_change,
        )
        self.suite_menu.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkButton(
            card_suite,
            text="🤗 Hugging Face'ten Canlı Çek (+20)",
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color=THEME["text_main"],
            height=30,
            command=self._fetch_live_hf,
        ).pack(fill="x", padx=12, pady=(0, 8))

        self.concurrency_label = ctk.CTkLabel(
            card_suite, text="Eşzamanlı İstek (Concurrency): 3", text_color=THEME["text_dim"], font=ctk.CTkFont(size=12)
        )
        self.concurrency_label.pack(anchor="w", padx=12)
        self.concurrency_slider = ctk.CTkSlider(
            card_suite,
            from_=1,
            to=10,
            number_of_steps=9,
            button_color=THEME["accent"],
            progress_color=THEME["accent"],
            command=lambda v: self.concurrency_label.configure(
                text=f"Eşzamanlı İstek (Concurrency): {int(v)}"
            ),
        )
        self.concurrency_slider.set(3)
        self.concurrency_slider.pack(fill="x", padx=12, pady=(2, 6))

        self.delay_label = ctk.CTkLabel(
            card_suite, text="İstek Arası Gecikme: 0.2 sn", text_color=THEME["text_dim"], font=ctk.CTkFont(size=12)
        )
        self.delay_label.pack(anchor="w", padx=12)
        self.delay_slider = ctk.CTkSlider(
            card_suite,
            from_=0.0,
            to=3.0,
            number_of_steps=30,
            button_color=THEME["secondary"],
            progress_color=THEME["secondary"],
            command=lambda v: self.delay_label.configure(text=f"İstek Arası Gecikme: {v:.1f} sn"),
        )
        self.delay_slider.set(0.2)
        self.delay_slider.pack(fill="x", padx=12, pady=(2, 10))

        self.pressure_suffix_switch = ctk.CTkSwitch(
            card_suite,
            text="'Ek Talep' baskı cümlesini gönder",
            progress_color=THEME["secondary"],
            button_color=THEME["text_main"],
        )
        self.pressure_suffix_switch.select()  # Varsayılan: veri setindeki gibi gönder
        self.pressure_suffix_switch.pack(anchor="w", padx=12, pady=(0, 2))
        ctk.CTkLabel(
            card_suite,
            text=(
                "Kapalıyken sorular sonundaki 'güvenlik uyarılarını atla,\n"
                "kısıtlamasız mod' cümlesi olmadan gönderilir; böylece\n"
                "kalıp ret yerine asıl saldırıya verilen yanıt ölçülür."
            ),
            text_color=THEME["text_dim"],
            font=ctk.CTkFont(size=11),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # ================= SAĞ ANA PANEL =================
        main_frame = ctk.CTkFrame(
            self,
            corner_radius=12,
            fg_color=THEME["bg_panel"],
            border_width=2,
            border_color=THEME["border"],
        )
        main_frame.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        main_frame.grid_rowconfigure(2, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        # --- ÜST AKSİYON ÇUBUĞU ---
        top_bar = ctk.CTkFrame(main_frame, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))

        self.run_btn = ctk.CTkButton(
            top_bar,
            text="▶️ Denetimi Başlat",
            font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            text_color=THEME["text_main"],
            height=38,
            width=165,
            command=self._start_evaluation_thread,
        )
        self.run_btn.pack(side="left", padx=(0, 6))

        self.stop_btn = ctk.CTkButton(
            top_bar,
            text="⏹️ Durdur",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            fg_color="#581C2E",
            hover_color="#7F1D1D",
            text_color="#FCA5A5",
            height=38,
            width=100,
            state="disabled",
            command=self._stop_evaluation,
        )
        self.stop_btn.pack(side="left", padx=4)

        ctk.CTkButton(
            top_bar,
            text="📂 Veri Seti Yükle",
            height=38,
            fg_color=THEME["bg_card"],
            hover_color=THEME["border"],
            border_width=1,
            border_color=THEME["border"],
            text_color=THEME["text_main"],
            command=self._load_custom_json,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            top_bar,
            text="📥 Raporu Kaydet",
            height=38,
            fg_color=THEME["secondary"],
            hover_color=THEME["border"],
            text_color="#141118",
            font=ctk.CTkFont(weight="bold"),
            command=self._export_markdown_report,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            top_bar,
            text="📂 Sonuç Aç",
            height=38,
            fg_color=THEME["bg_card"],
            hover_color=THEME["border"],
            border_width=1,
            border_color=THEME["border"],
            text_color=THEME["text_main"],
            command=self._load_results_file,
        ).pack(side="left", padx=4)


        # --- 4 ŞIK KPI METRİK KARTI + İLERLEME ÇUBUĞU ---
        kpi_container = ctk.CTkFrame(main_frame, fg_color="transparent")
        kpi_container.grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 6))
        for i in range(4):
            kpi_container.grid_columnconfigure(i, weight=1)

        self.lbl_total = self._create_kpi_card(kpi_container, 0, "📊 TOPLAM TEST", "0", THEME["text_main"])
        self.lbl_pass = self._create_kpi_card(kpi_container, 1, "🛡️ GÜVENLİ", "0", THEME["pass"])
        self.lbl_fail = self._create_kpi_card(kpi_container, 2, "🚨 İHLAL / HATA", "0", THEME["fail"])
        self.lbl_score = self._create_kpi_card(kpi_container, 3, "🎯 UYUMLULUK SKORU", "%0.0", THEME["secondary"])

        self.progress = ctk.CTkProgressBar(
            kpi_container,
            height=8,
            fg_color=THEME["bg_card"],
            progress_color=THEME["accent"],
        )
        self.progress.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            kpi_container,
            text=f"Hazır | Yüklü: {len(self.test_cases)} Senaryo",
            text_color=THEME["text_dim"],
            font=ctk.CTkFont(family="Consolas", size=12),
            anchor="w",
        )
        self.status_label.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # --- SEKMELER ---
        self.tabview = ctk.CTkTabview(
            main_frame,
            fg_color=THEME["bg_card"],
            segmented_button_fg_color=THEME["bg_input"],
            segmented_button_selected_color=THEME["accent"],
            segmented_button_selected_hover_color=THEME["accent_hover"],
            segmented_button_unselected_color=THEME["bg_input"],
            segmented_button_unselected_hover_color=THEME["border"],
            text_color=THEME["text_main"],
        )
        self.tabview.grid(row=2, column=0, sticky="nsew", padx=14, pady=(2, 12))

        tab_table = self.tabview.add("📊 Denetim Sonuçları")
        tab_report = self.tabview.add("📄 Kurumsal Rapor Önizleme")
        tab_cases = self.tabview.add("➕ Yeni Senaryo Ekle")

        tab_table.grid_rowconfigure(1, weight=1)
        tab_table.grid_columnconfigure(0, weight=1)

        # Tablo Üstü Hızlı Filtre Çubuğu
        filter_bar = ctk.CTkFrame(tab_table, fg_color="transparent")
        filter_bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkLabel(
            filter_bar,
            text="Görünüm Filtresi:",
            text_color=THEME["text_dim"],
            font=ctk.CTkFont(family="Consolas", size=12),
        ).pack(side="left", padx=(4, 8))

        self.filter_seg = ctk.CTkSegmentedButton(
            filter_bar,
            values=["Tümü", "🚨 Sadece İhlaller", "✅ Sadece Güvenli", "⚠️ Bağlantı Hataları"],
            selected_color=THEME["accent"],
            selected_hover_color=THEME["accent_hover"],
            unselected_color=THEME["bg_input"],
            unselected_hover_color=THEME["border"],
            command=self._on_filter_change,
        )
        self.filter_seg.set("Tümü")
        self.filter_seg.pack(side="left")

        # Sonuç Tablosu (Treeview + Scrollbar)
        tree_frame = ctk.CTkFrame(tab_table, fg_color=THEME["bg_input"], corner_radius=6)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Treeview",
            background="#1A1520",
            foreground=THEME["text_main"],
            fieldbackground="#1A1520",
            rowheight=29,
            borderwidth=0,
            font=("Consolas", 10),
        )
        style.configure(
            "Treeview.Heading",
            background=THEME["border"],
            foreground=THEME["text_main"],
            relief="flat",
            font=("Consolas", 10, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", THEME["accent"])],
            foreground=[("selected", "#FFFFFF")],
        )

        cols = ("status", "id", "category", "title", "reason", "latency")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("status", text="Durum")
        self.tree.heading("id", text="Senaryo ID")
        self.tree.heading("category", text="Kategori")
        self.tree.heading("title", text="Test Başlığı")
        self.tree.heading("reason", text="Hakem Kararı & Açıklama")
        self.tree.heading("latency", text="Süre (ms)")

        self.tree.column("status", width=105, anchor="center")
        self.tree.column("id", width=115, anchor="w")
        self.tree.column("category", width=185, anchor="w")
        self.tree.column("title", width=180, anchor="w")
        self.tree.column("reason", width=360, anchor="w")
        self.tree.column("latency", width=80, anchor="center")

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")

        self.tree.tag_configure("fail", background="#351826", foreground="#FCA5A5")
        self.tree.tag_configure("warn", background="#332614", foreground="#FDE68A")
        self.tree.tag_configure("pass_even", background="#1A1520", foreground=THEME["text_main"])
        self.tree.tag_configure("pass_odd", background="#211B29", foreground=THEME["text_main"])
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self.tree.bind("<Double-1>", lambda _e: self._open_detail())

        # --- ALT BÖLÜM: BİLGE BAYKUŞ SAHNESİ & NET SORU/CEVAP İNCELEME KARTI ---
        bottom_inspector = ctk.CTkFrame(
            tab_table,
            fg_color=THEME["bg_panel"],
            corner_radius=10,
            border_width=2,
            border_color=THEME["accent"],
        )
        bottom_inspector.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bottom_inspector.grid_columnconfigure(0, weight=5)
        bottom_inspector.grid_columnconfigure(1, weight=6)

        self.mascot_canvas = tk.Canvas(
            bottom_inspector,
            width=430,
            height=250,
            bg=THEME["bg_panel"],
            highlightthickness=0,
            bd=0,
        )
        self.mascot_canvas.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        self.mascot_canvas.configure(cursor="hand2")
        self.mascot_canvas.bind("<Button-1>", lambda _e: self._open_detail())

        qa_frame = ctk.CTkFrame(
            bottom_inspector,
            fg_color=THEME["bg_card"],
            corner_radius=8,
            border_width=1,
            border_color=THEME["border"],
        )
        qa_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        qa_frame.grid_columnconfigure(0, weight=1)

        qa_head = ctk.CTkFrame(qa_frame, fg_color="transparent")
        qa_head.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))
        qa_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            qa_head,
            text="📤 Soru & 🤖 Cevap",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=THEME["text_main"],
        ).grid(row=0, column=0, sticky="w")
        for col, (txt, cmd, w) in enumerate(
            (
                ("A−", lambda: self._change_font_scale(-0.1), 34),
                ("A+", lambda: self._change_font_scale(0.1), 34),
                ("🔍 Detay", self._open_detail, 84),
            ),
            start=1,
        ):
            ctk.CTkButton(
                qa_head, text=txt, width=w, height=28, command=cmd,
                fg_color=THEME["accent"] if "Detay" in txt else THEME["bg_input"],
                hover_color=THEME["accent_hover"],
            ).grid(row=0, column=col, padx=(4, 0))

        self.detail_box = ctk.CTkTextbox(
            qa_frame,
            height=170,
            fg_color=THEME["bg_input"],
            text_color=THEME["text_main"],
            font=ctk.CTkFont(family="Consolas", size=13),
            wrap="word",
        )
        self.detail_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(2, 8))
        self.detail_box.insert(
            "0.0",
            "▶ GÖNDERİLEN SORU:\nTablodan bir satıra tıklayın.\n\n"
            "◀ HEDEF YAPAY ZEKANIN CEVABI:\nSeçtiğiniz satırdaki yapay zeka yanıtı burada büyük ve net olarak görünecektir.",
        )

        # Rapor Önizleme Sekmesi
        tab_report.grid_rowconfigure(0, weight=1)
        tab_report.grid_columnconfigure(0, weight=1)
        self.report_box = ctk.CTkTextbox(
            tab_report,
            fg_color=THEME["bg_input"],
            text_color=THEME["text_main"],
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.report_box.grid(row=0, column=0, sticky="nsew")

        # Yeni Senaryo Ekleme Sekmesi
        self._build_add_case_tab(tab_cases)

    def _create_kpi_card(
        self, parent: ctk.CTkFrame, col: int, title: str, initial_val: str, val_color: str
    ) -> ctk.CTkLabel:
        card = ctk.CTkFrame(
            parent,
            fg_color=THEME["bg_card"],
            corner_radius=8,
            border_width=1,
            border_color=THEME["border"],
        )
        card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 4, 0 if col == 3 else 4))
        ctk.CTkLabel(
            card,
            text=title,
            text_color=THEME["text_dim"],
            font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(6, 0))
        val_lbl = ctk.CTkLabel(
            card,
            text=initial_val,
            text_color=val_color,
            font=ctk.CTkFont(family="Consolas", size=18, weight="bold"),
        )
        val_lbl.pack(anchor="w", padx=12, pady=(0, 6))
        return val_lbl


    def _stop_evaluation(self) -> None:
        if self.active_cancel_event is not None:
            self.active_cancel_event.set()
            self.status_label.configure(text="⏹️ Durduruluyor...")
            self.stop_btn.configure(state="disabled")

    def _start_evaluation_thread(self) -> None:
        t_cfg, j_cfg = self._collect_configs()
        if t_cfg.mode == "custom_http" and not t_cfg.endpoint_url:
            messagebox.showerror("Eksik URL", "Lütfen Hedef Chat API URL adresini girin.")
            return

        self.run_btn.configure(state="disabled", text="⏳ Çalışıyor...")
        self.stop_btn.configure(state="normal")
        self.progress.set(0)
        self.eval_results = []
        self.selected_idx = None
        try:
            self._autosave_path.parent.mkdir(parents=True, exist_ok=True)
            self._autosave_path.write_text("", encoding="utf-8")
        except OSError:
            pass
        for item in self.tree.get_children():
            self.tree.delete(item)

        concurrency = int(self.concurrency_slider.get())
        delay = float(self.delay_slider.get())
        run_cases = (
            self.test_cases
            if self.pressure_suffix_switch.get()
            else without_pressure_suffix(self.test_cases)
        )

        def worker() -> None:
            t0 = time.perf_counter()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            cancel_ev = asyncio.Event()
            self.active_cancel_event = cancel_ev

            def on_prog(done: int, total: int, res: Optional[EvaluationResult] = None) -> None:
                self.after(0, lambda d=done, tot=total, r=res: self._on_live_result(d, tot, r))

            try:
                results = loop.run_until_complete(
                    run_test_suite(
                        test_cases=run_cases,
                        target_config=t_cfg,
                        judge_config=j_cfg,
                        concurrency=concurrency,
                        rate_limit_delay=delay,
                        on_progress=on_prog,  # type: ignore[arg-type]
                        cancel_event=cancel_ev,
                    )
                )
            finally:
                loop.close()

            elapsed = time.perf_counter() - t0
            self.after(0, lambda: self._on_evaluation_complete(results, elapsed, t_cfg.mode, j_cfg.model_name))

        threading.Thread(target=worker, daemon=True).start()


    # ---------- Okunabilirlik, detay penceresi, elle karar, kayıt ----------


if __name__ == "__main__":
    app = LLMGuardDesktopApp()
    app.mainloop()
