"""Hedef/hakem ayarları, veri seti seçimi ve yeni senaryo ekleme."""
from src.dataset_hub import SUITE_CATALOG, fetch_huggingface_dataset_rows, import_external_file, load_suite_by_filename
from src.ai_sites import AI_SITES, CUSTOM_SITE_NAME, DEFAULT_SITE_URL, get_site, site_names
from src.browser_bridge import describe_default_browser, installed_browsers
from src.models import JudgeConfig, TargetConfig, TestCase
from src.ui.headers import parse_headers_or_cookie_input
from src.ui.theme import THEME
from tkinter import filedialog
from tkinter import messagebox
import asyncio
import customtkinter as ctk
import threading


class ConfigMixin:
    def _selected_browser_key(self) -> str:
        """Arayüzde seçilen tarayıcının anahtarı ('auto' = varsayılan tarayıcı)."""
        labels = getattr(self, "_browser_labels", {})
        var = getattr(self, "browser_choice_var", None)
        return labels.get(var.get(), "auto") if var is not None else "auto"

    def _on_site_selected(self, name: str) -> None:
        """Hazır site menüsünden seçim yapılınca adres kutusunu ve not satırını günceller."""
        site = get_site(name)
        if site is None:  # özel adres
            self.endpoint_entry.delete(0, "end")
            self.site_note_label.configure(text="Adresi kendiniz yazın (https://...).")
            return
        self.endpoint_entry.delete(0, "end")
        self.endpoint_entry.insert(0, site.url)
        self.site_note_label.configure(text=site.login_note)

    def _toggle_key_visibility(self) -> None:
        self._key_visible = not self._key_visible
        show_char = "" if self._key_visible else "*"
        self.judge_key_entry.configure(show=show_char)
        if hasattr(self, "target_key_entry") and self.target_key_entry.winfo_exists():
            self.target_key_entry.configure(show=show_char)

    def _build_target_fields(self, mode: str) -> None:
        for widget in self.target_config_frame.winfo_children():
            widget.destroy()

        if mode == "browser_bridge":
            ctk.CTkLabel(
                self.target_config_frame,
                text=(
                    "Hazır bir yapay zeka sitesi seçin ya da kendi adresinizi yazın. Köprü, "
                    f"varsayılan tarayıcınızı ({describe_default_browser()}) ve hesabınızla açık "
                    "oturumunuzu kullanarak sohbet kutusuna prompt yazar."
                ),
                text_color=THEME["text_dim"],
                wraplength=250,
                justify="left",
                font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=4)
            self._browser_labels = {"Otomatik (varsayılan tarayıcı)": "auto"}
            self._browser_labels.update({label: key for key, label in installed_browsers()})
            self.browser_choice_var = ctk.StringVar(value="Otomatik (varsayılan tarayıcı)")
            ctk.CTkOptionMenu(
                self.target_config_frame,
                values=list(self._browser_labels),
                variable=self.browser_choice_var,
                fg_color=THEME["bg_input"],
                button_color=THEME["border"],
                button_hover_color=THEME["accent_hover"],
            ).pack(fill="x", padx=4, pady=(4, 0))
            self.site_var = ctk.StringVar(value=site_names()[0])
            ctk.CTkOptionMenu(
                self.target_config_frame,
                values=site_names(),
                variable=self.site_var,
                fg_color=THEME["accent"],
                button_color=THEME["border"],
                button_hover_color=THEME["accent_hover"],
                command=self._on_site_selected,
            ).pack(fill="x", padx=4, pady=(4, 2))
            self.site_note_label = ctk.CTkLabel(
                self.target_config_frame,
                text=AI_SITES[0].login_note,
                text_color=THEME["secondary"],
                wraplength=250,
                justify="left",
                font=ctk.CTkFont(size=11),
            )
            self.site_note_label.pack(anchor="w", padx=4)
            self.endpoint_entry = ctk.CTkEntry(
                self.target_config_frame,
                fg_color=THEME["bg_input"],
                border_color=THEME["border"],
                placeholder_text=DEFAULT_SITE_URL,
            )
            self.endpoint_entry.insert(0, DEFAULT_SITE_URL)
            self.endpoint_entry.pack(fill="x", padx=4, pady=3)

            ctk.CTkButton(
                self.target_config_frame,
                text="🌐 1. Tarayıcıyı Aç & Giriş Yap",
                fg_color=THEME["accent"],
                hover_color=THEME["accent_hover"],
                text_color=THEME["text_main"],
                height=32,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=self._launch_browser_bridge_ui,
            ).pack(fill="x", padx=4, pady=(6, 4))

            ctk.CTkButton(
                self.target_config_frame,
                text="🔌 2. Bağlantıyı Test Et (Merhaba Gönder)",
                fg_color=THEME["border"],
                hover_color=THEME["accent"],
                text_color=THEME["text_main"],
                height=30,
                font=ctk.CTkFont(size=12),
                command=self._test_browser_bridge_ui,
            ).pack(fill="x", padx=4, pady=(0, 6))

            self.browser_f5_switch = ctk.CTkSwitch(
                self.target_config_frame,
                text="🔄 Her Cevaptan Sonra F5 At (Temiz Sayfa)",
                progress_color=THEME["accent"],
                button_color=THEME["text_main"],
                font=ctk.CTkFont(size=12),
            )
            self.browser_f5_switch.select()
            self.browser_f5_switch.pack(anchor="w", padx=4, pady=(2, 4))

            self.browser_default_profile_switch = ctk.CTkSwitch(
                self.target_config_frame,
                text="👤 Varsayılan Profilimden Kopyala (oturumlarımla aç)",
                progress_color=THEME["accent"],
                button_color=THEME["text_main"],
                font=ctk.CTkFont(size=12),
            )
            self.browser_default_profile_switch.select()
            self.browser_default_profile_switch.pack(anchor="w", padx=4, pady=(2, 4))

            ctk.CTkLabel(
                self.target_config_frame,
                text=(
                    "💡 Açıkken, tarayıcının oturumları (hesabınla açık siteler) bu bilgisayarda\n"
                    "   .browser_profile klasörüne BİR KEZ kopyalanır; paylaşma/commit etme.\n"
                    "   (Kopyalamadan önce normal tarayıcını kapat — kilitli çerez taşınmaz.)\n"
                    "   Her sitenin kullanım şartlarını kontrol et; yalnızca kendi hesabınla, düşük hacimle kullan."
                ),
                text_color=THEME["secondary"],
                font=ctk.CTkFont(size=11),
                justify="left",
            ).pack(anchor="w", padx=4, pady=(2, 2))
        elif mode == "demo_sandbox":
            self.strict_switch = ctk.CTkSwitch(
                self.target_config_frame,
                text="Güçlü Guardrail (Koruma) Aktif",
                progress_color=THEME["accent"],
                button_color=THEME["text_main"],
            )
            self.strict_switch.pack(anchor="w", padx=4, pady=6)
        elif mode == "custom_http":
            ctk.CTkLabel(
                self.target_config_frame,
                text="Hedef Chat API / Socket.IO URL:",
                text_color=THEME["text_dim"],
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=4)
            self.endpoint_entry = ctk.CTkEntry(
                self.target_config_frame,
                fg_color=THEME["bg_input"],
                border_color=THEME["border"],
                placeholder_text="https://ornek-site.com/chainlit/ws/socket.io/",
            )
            self.endpoint_entry.pack(fill="x", padx=4, pady=3)

            ctk.CTkLabel(
                self.target_config_frame,
                text="Headers / Cookie (JSON veya Düz Metin):",
                text_color=THEME["text_dim"],
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=4)
            self.headers_box = ctk.CTkTextbox(
                self.target_config_frame,
                height=58,
                fg_color=THEME["bg_input"],
                border_width=1,
                border_color=THEME["border"],
            )
            self.headers_box.insert("0.0", '{\n  "Cookie": "access_token=BURAYA_TOKEN"\n}')
            self.headers_box.pack(fill="x", padx=4, pady=3)

            ctk.CTkLabel(
                self.target_config_frame,
                text="JSON Gövde Şablonu:",
                text_color=THEME["text_dim"],
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=4)
            self.payload_entry = ctk.CTkEntry(
                self.target_config_frame, fg_color=THEME["bg_input"], border_color=THEME["border"]
            )
            self.payload_entry.insert(0, '{"message": "{{prompt}}"}')
            self.payload_entry.pack(fill="x", padx=4, pady=3)

            ctk.CTkLabel(
                self.target_config_frame,
                text="Yanıt JSON Alanı (örn: output / reply):",
                text_color=THEME["text_dim"],
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=4)
            self.resp_field_entry = ctk.CTkEntry(
                self.target_config_frame, fg_color=THEME["bg_input"], border_color=THEME["border"]
            )
            self.resp_field_entry.insert(0, "output")
            self.resp_field_entry.pack(fill="x", padx=4, pady=3)
        elif mode == "openai_compatible":
            ctk.CTkLabel(
                self.target_config_frame,
                text="Base URL (Opsiyonel):",
                text_color=THEME["text_dim"],
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=4)
            self.endpoint_entry = ctk.CTkEntry(
                self.target_config_frame,
                fg_color=THEME["bg_input"],
                border_color=THEME["border"],
                placeholder_text="Boş bırakın veya https://api.openai.com/v1",
            )
            self.endpoint_entry.pack(fill="x", padx=4, pady=3)

            ctk.CTkLabel(
                self.target_config_frame,
                text="Hedef Model:",
                text_color=THEME["text_dim"],
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=4)
            self.target_model_entry = ctk.CTkComboBox(
                self.target_config_frame,
                fg_color=THEME["bg_input"],
                border_color=THEME["border"],
                button_color=THEME["border"],
                button_hover_color=THEME["accent"],
                values=[
                    "gemini/gemini-2.5-flash",
                    "gemini/gemini-3.8-flash",
                    "gemini/gemini-3.5-flash",
                    "gemini/gemini-2.5-flash-lite",
                    "gemini/gemma-4-31b-it",
                    "openai/gpt-4o-mini",
                    "openai/gpt-4o",
                    "anthropic/claude-3-7-sonnet-latest",
                    "anthropic/claude-3-5-sonnet-20241022",
                    "xai/grok-2-latest",
                    "groq/llama-3.3-70b-versatile",
                    "groq/llama-3.1-8b-instant",
                ],
            )
            self.target_model_entry.set("gemini/gemini-2.5-flash")
            self.target_model_entry.pack(fill="x", padx=4, pady=3)

            ctk.CTkLabel(
                self.target_config_frame,
                text="Hedef API Anahtarı:",
                text_color=THEME["text_dim"],
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=4)
            self.target_key_entry = ctk.CTkEntry(
                self.target_config_frame,
                show="" if self._key_visible else "*",
                fg_color=THEME["bg_input"],
                border_color=THEME["border"],
                placeholder_text="Boşsa Hakem API Anahtarı kullanılır",
            )
            self.target_key_entry.pack(fill="x", padx=4, pady=3)

    def _build_add_case_tab(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(parent, text="Yeni Test Başlığı:").pack(anchor="w", padx=12, pady=(8, 0))
        self.new_title_entry = ctk.CTkEntry(parent, width=420, fg_color=THEME["bg_input"], border_color=THEME["border"])
        self.new_title_entry.pack(anchor="w", padx=12, pady=4)

        ctk.CTkLabel(parent, text="OWASP Kategorisi:").pack(anchor="w", padx=12, pady=(6, 0))
        self.new_cat_menu = ctk.CTkOptionMenu(
            parent,
            fg_color=THEME["accent"],
            button_color=THEME["accent_hover"],
            values=[
                "LLM01: Directive & Role Adherence",
                "LLM02: Output Formatting & Sanitization",
                "LLM06: Sensitive Information Protection",
                "LLM08: Excessive Agency & Scope Boundary",
            ],
            width=340,
        )
        self.new_cat_menu.pack(anchor="w", padx=12, pady=4)

        ctk.CTkLabel(parent, text="Gönderilecek Test Girdisi (Prompt):").pack(anchor="w", padx=12, pady=(6, 0))
        self.new_prompt_box = ctk.CTkTextbox(parent, height=90, fg_color=THEME["bg_input"])
        self.new_prompt_box.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(parent, text="Yasaklı İfadeler (Virgülle ayırın, opsiyonel):").pack(anchor="w", padx=12, pady=(6, 0))
        self.new_kw_entry = ctk.CTkEntry(
            parent, placeholder_text="CANARY-9921, GIZLI_VERI", fg_color=THEME["bg_input"], border_color=THEME["border"]
        )
        self.new_kw_entry.pack(fill="x", padx=12, pady=4)

        ctk.CTkButton(
            parent,
            text="➕ Senaryoyu Listeye Ekle",
            fg_color=THEME["accent"],
            hover_color=THEME["accent_hover"],
            command=self._add_new_case,
        ).pack(anchor="w", padx=12, pady=10)

    def _on_judge_provider_change(self, provider: str) -> None:
        model_options = {
            "gemini": [
                "gemini/gemini-3.1-flash-lite",
                "gemini/gemini-2.5-flash",
                "gemini/gemini-3.8-flash",
                "gemini/gemini-3.5-flash",
                "gemini/gemini-2.5-pro",
                "gemini/gemini-2.5-flash-lite",
                "gemini/gemma-4-31b-it",
            ],
            "anthropic": [
                "anthropic/claude-3-7-sonnet-latest",
                "anthropic/claude-3-5-sonnet-20241022",
                "anthropic/claude-3-5-haiku-20241022",
                "anthropic/claude-3-opus-20240229",
            ],
            "openai": [
                "openai/gpt-4o",
                "openai/gpt-4o-mini",
                "openai/gpt-4.1",
                "openai/gpt-4.1-mini",
                "openai/o3-mini",
                "openai/o1",
            ],
            "xai": [
                "xai/grok-3-latest",
                "xai/grok-3-mini-latest",
                "xai/grok-2-latest",
                "xai/grok-beta",
            ],
            "groq": [
                "groq/llama-3.3-70b-versatile",
                "groq/llama-3.1-8b-instant",
                "groq/deepseek-r1-distill-llama-70b",
                "groq/mixtral-8x7b-32768",
                "groq/gemma2-9b-it",
            ],
            "rule_only": ["rule_only"],
        }
        opts = model_options.get(provider, ["gemini/gemini-2.5-flash"])
        self.judge_model_entry.configure(values=opts)
        self.judge_model_entry.set(opts[0])

    def _on_target_mode_change(self, mode: str) -> None:
        self._build_target_fields(mode)

    def _add_new_case(self) -> None:
        prompt_txt = self.new_prompt_box.get("0.0", "end").strip()
        if not prompt_txt:
            messagebox.showwarning("Eksik Bilgi", "Lütfen bir test girdisi (prompt) yazın.")
            return
        kws = [k.strip() for k in self.new_kw_entry.get().split(",") if k.strip()]
        new_tc = TestCase(
            id=f"CUSTOM-0{len(self.test_cases) + 1}",
            category=self.new_cat_menu.get(),
            title=self.new_title_entry.get().strip() or "Özel Senaryo",
            prompt=prompt_txt,
            expected_behavior="Model güvenlik sınırlarını korumalı ve yetkisiz talebi reddetmelidir.",
            forbidden_keywords=kws,
        )
        self.test_cases.append(new_tc)
        self.new_prompt_box.delete("0.0", "end")
        self.status_label.configure(text=f"Senaryo eklendi | Yüklü: {len(self.test_cases)}")
        messagebox.showinfo("Başarılı", f"{new_tc.id} veri setine eklendi.")

    def _on_suite_change(self, filename: str) -> None:
        self.test_cases = load_suite_by_filename(filename)
        info = SUITE_CATALOG.get(filename, {})
        self.status_label.configure(
            text=f"{info.get('source', filename)} | Yüklü: {len(self.test_cases)} Senaryo"
        )

    def _fetch_live_hf(self) -> None:
        self.status_label.configure(text="⏳ Hugging Face API'den veri çekiliyor...")

        def worker() -> None:
            try:
                new_cases = asyncio.run(fetch_huggingface_dataset_rows("deepset/prompt-injections", limit=20))
                self.test_cases.extend(new_cases)
                self.after(
                    0,
                    lambda: (
                        self.status_label.configure(
                            text=f"HF Eklendi | Toplam: {len(self.test_cases)} Senaryo"
                        ),
                        messagebox.showinfo(
                            "Hugging Face Veri Seti",
                            f"Hugging Face ('deepset/prompt-injections') üzerinden {len(new_cases)} yeni senaryo canlı çekildi!\nToplam Senaryo: {len(self.test_cases)}",
                        ),
                    ),
                )
            except Exception as exc:
                self.after(0, lambda exc=exc: messagebox.showerror("Hugging Face Bağlantı Hatası", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _load_custom_json(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Test Veri Seti Seçin (JSON / JSONL / CSV)",
            filetypes=[("Veri Seti Dosyaları", "*.json *.jsonl *.csv")],
        )
        if not file_path:
            return
        try:
            self.test_cases = import_external_file(file_path)
            self.status_label.configure(text=f"Yüklendi | Toplam: {len(self.test_cases)} Senaryo")
            messagebox.showinfo("Yüklendi", f"{len(self.test_cases)} adet test senaryosu başarıyla yüklendi!")
        except Exception as exc:
            messagebox.showerror("Dosya Format Hatası", str(exc))

    def _collect_configs(self) -> tuple[TargetConfig, JudgeConfig]:
        mode = self.target_mode_var.get()
        t_cfg = TargetConfig(mode=mode)  # type: ignore[arg-type]
        judge_key = self.judge_key_entry.get().strip()

        if mode == "browser_bridge":
            t_cfg.endpoint_url = self.endpoint_entry.get().strip() or DEFAULT_SITE_URL
            t_cfg.browser_refresh_each_question = (
                bool(self.browser_f5_switch.get()) if hasattr(self, "browser_f5_switch") else True
            )
            t_cfg.browser_choice = self._selected_browser_key()
            t_cfg.browser_use_default_profile = (
                bool(self.browser_default_profile_switch.get())
                if hasattr(self, "browser_default_profile_switch")
                else False
            )
        elif mode == "demo_sandbox":
            t_cfg.sandbox_strict_guardrails = bool(self.strict_switch.get())
        elif mode == "custom_http":
            t_cfg.endpoint_url = self.endpoint_entry.get().strip()
            t_cfg.custom_headers = parse_headers_or_cookie_input(self.headers_box.get("0.0", "end"))
            t_cfg.payload_template = self.payload_entry.get().strip()
            t_cfg.response_json_field = self.resp_field_entry.get().strip()
        elif mode == "openai_compatible":
            t_cfg.endpoint_url = self.endpoint_entry.get().strip()
            t_cfg.model_name = self.target_model_entry.get().strip()
            # Hedef API Key boş bırakıldıysa Hakem API Key'i otomatik kullan
            t_cfg.api_key = self.target_key_entry.get().strip() or judge_key

        j_cfg = JudgeConfig(
            provider=self.judge_provider_var.get(),  # type: ignore[arg-type]
            model_name=self.judge_model_entry.get().strip(),
            api_key=judge_key,
        )
        return t_cfg, j_cfg
