"""Tarayıcı köprüsünü (Browser Bridge) açma ve test etme düğmeleri."""
from src.ai_sites import DEFAULT_SITE_URL
from src.browser_bridge import launch_browser_bridge, query_browser_bridge
from tkinter import messagebox
import asyncio
import threading
import time


class BridgeMixin:
    def _launch_browser_bridge_ui(self) -> None:
        target_url = (
            self.endpoint_entry.get().strip()
            if hasattr(self, "endpoint_entry") and self.endpoint_entry.winfo_exists()
            else DEFAULT_SITE_URL
        ) or DEFAULT_SITE_URL
        browser_key = self._selected_browser_key()
        use_default_profile = (
            bool(self.browser_default_profile_switch.get())
            if hasattr(self, "browser_default_profile_switch")
            else False
        )
        if use_default_profile:
            self.status_label.configure(text=f"🌐 Profil kopyalanıyor ve tarayıcı açılıyor ({target_url})...")
        else:
            self.status_label.configure(text=f"🌐 Tarayıcı başlatılıyor ({target_url})...")

        def worker() -> None:
            try:
                msg = asyncio.run(
                    launch_browser_bridge(
                        target_url, use_default_profile=use_default_profile, browser_key=browser_key
                    )
                )
                self.after(
                    0,
                    lambda: (
                        self.status_label.configure(text=f"🌐 {msg}"),
                        setattr(self, "mascot_mood", "happy"),
                        setattr(self, "bubble_title", "🌐 TARAYICI KÖPRÜSÜ AÇILDI!"),
                        setattr(
                            self,
                            "bubble_text",
                            f"{msg} Açılan pencerede sohbet ekranı hazırsa '🔌 2. Bağlantıyı Test Et' veya '▶️ Denetimi Başlat' butonuna basabilirsin!",
                        ),
                    ),
                )
            except Exception as exc:
                self.after(
                    0,
                    lambda exc=exc: (
                        self.status_label.configure(text="❌ Tarayıcı başlatılamadı"),
                        messagebox.showerror("Tarayıcı Köprüsü Hatası", str(exc)),
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _test_browser_bridge_ui(self) -> None:
        target_url = (
            self.endpoint_entry.get().strip()
            if hasattr(self, "endpoint_entry") and self.endpoint_entry.winfo_exists()
            else DEFAULT_SITE_URL
        ) or DEFAULT_SITE_URL
        browser_key = self._selected_browser_key()
        use_default_profile = (
            bool(self.browser_default_profile_switch.get())
            if hasattr(self, "browser_default_profile_switch")
            else False
        )
        test_prompt = "Merhaba! Bu bir bağlantı testidir, lütfen kısaca sesimi duyduğunu onayla."
        self.status_label.configure(text="🔌 Tarayıcıya test mesajı gönderiliyor...")

        def worker() -> None:
            t0 = time.perf_counter()
            try:
                reply = asyncio.run(
                    query_browser_bridge(
                        test_prompt,
                        target_url=target_url,
                        timeout_sec=30.0,
                        use_default_profile=use_default_profile,
                        browser_key=browser_key,
                    )
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000
                self.after(
                    0,
                    lambda: (
                        self.status_label.configure(text=f"✅ Köprü Testi Başarılı ({elapsed_ms:.0f} ms)"),
                        setattr(self, "mascot_mood", "happy"),
                        setattr(self, "bubble_title", f"✅ TARAYICI KÖPRÜSÜ ÇALIŞIYOR! ({elapsed_ms:.0f} ms)"),
                        setattr(
                            self,
                            "bubble_text",
                            f"Hedef sohbet ekranından gerçek yanıt başarıyla okundu: \"{reply[:180]}\"",
                        ),
                        self.detail_box.delete("0.0", "end"),
                        self.detail_box.insert(
                            "0.0",
                            f"▶ GÖNDERİLEN TEST SORUSU:\n{test_prompt}\n\n"
                            f"◀ TARAYICIDAN OKUNAN GERÇEK CEVAP ({elapsed_ms:.0f} ms):\n{reply}",
                        ),
                        messagebox.showinfo(
                            "✅ Tarayıcı Köprüsü Başarılı",
                            f"Soru tarayıcıya yazıldı ve gerçek yanıt okundu ({elapsed_ms:.0f} ms):\n\n{reply[:500]}",
                        ),
                    ),
                )
            except Exception as exc:
                self.after(
                    0,
                    lambda exc=exc: (
                        self.status_label.configure(text="❌ Köprü Testi Başarısız"),
                        setattr(self, "mascot_mood", "alert"),
                        setattr(self, "bubble_title", "⚠️ TARAYICI KÖPRÜSÜ YANIT ALAMADI"),
                        setattr(self, "bubble_text", str(exc)),
                        messagebox.showerror("Bağlantı Testi Hatası", str(exc)),
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()
