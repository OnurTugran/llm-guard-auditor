"""Sonuç tablosu, KPI, detay penceresi, elle karar, otomatik kayıt ve rapor dışa aktarma."""
from pathlib import Path
from src.detail_window import ResultDetailWindow
from src.models import EvaluationResult
from src.reporter import generate_markdown_report
from src.summary import AuditSummary, summarize
from src.ui.theme import THEME
from src.ui.theme import row_display
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
from typing import Optional
import customtkinter as ctk
import json


class ResultsMixin:
    def _on_live_result(self, done: int, total: int, res: Optional[EvaluationResult] = None) -> None:
        """Her soru tamamlandığında tabloyu, KPI kartlarını ve sağ alt inceleme kutusunu CANLI günceller."""
        self.progress.set(done / max(1, total))
        self.status_label.configure(text=f"Denetleniyor ({done}/{total})...")
        if res is None:
            return

        idx = len(self.eval_results)
        self.eval_results.append(res)
        self.selected_idx = idx
        self._autosave_result(res)

        # 1. Canlı KPI Kartlarını Güncelle
        self._update_kpis(self.eval_results)

        # 2. Tabloya Canlı Satır Ekle ve Kaydır
        status_str, row_kind = row_display(res)

        if self.current_filter in ("all", row_kind):
            visible_count = len(self.tree.get_children())
            tag = ("pass_even" if visible_count % 2 == 0 else "pass_odd") if row_kind == "pass" else row_kind
            iid = str(idx)
            self.tree.insert(
                "",
                "end",
                iid=iid,
                tags=(tag,),
                values=(
                    status_str,
                    res.test_case.id,
                    res.test_case.category,
                    res.test_case.title,
                    res.verdict.reason,
                    f"{res.latency_ms:.0f}",
                ),
            )
            self.tree.see(iid)

        # 3. Sağ Alt Soru/Cevap Kutusu ve Bilge Baykuş Balonunu Canlı Güncelle
        self.detail_box.delete("0.0", "end")
        self.detail_box.insert(
            "0.0",
            f"📌 CANLI TEST ({done}/{total}): [{res.test_case.id}] {res.test_case.title}\n"
            f"{'─' * 56}\n"
            f"📤 GÖNDERİLEN SORU (PROMPT):\n{res.test_case.prompt}\n\n"
            f"🤖 HEDEF YAPAY ZEKANIN CEVABI ({res.latency_ms:.0f} ms):\n{res.target_response or '(Yanıt alınamadı)'}",
        )

        if row_kind == "warn":
            self.mascot_mood = "alert"
            self.bubble_title = f"⚠️ [{res.test_case.id}] BAĞLANTI UYARISI ({done}/{total})"
            self.bubble_text = res.verdict.reason
        elif row_kind == "fail":
            self.mascot_mood = "alert"
            self.bubble_title = f"🚨 [{res.test_case.id}] CANLI İHLAL YAKALANDI! ({done}/{total})"
            self.bubble_text = f"\"{res.verdict.reason}\"\n(Kategori: {res.test_case.category})"
        else:
            self.mascot_mood = "happy"
            self.bubble_title = f"✅ [{res.test_case.id}] GÜVENLİ GEÇTİ ({done}/{total})"
            self.bubble_text = f"\"{res.verdict.reason}\""

    def _update_kpis(self, results: list[EvaluationResult]) -> AuditSummary:
        """KPI kartlarını özet istatistiklerle günceller (skor hesabı src/summary.py'de)."""
        summary = summarize(results)
        self.lbl_total.configure(text=str(summary.total))
        self.lbl_pass.configure(text=str(summary.passed))
        self.lbl_fail.configure(
            text=f"{summary.violated}" + (f" (+{summary.errors} Hata)" if summary.errors else "")
        )
        self.lbl_score.configure(text=f"%{summary.compliance_rate}")
        return summary

    def _on_filter_change(self, selected_label: str) -> None:
        mapping = {
            "Tümü": "all",
            "🚨 Sadece İhlaller": "fail",
            "✅ Sadece Güvenli": "pass",
            "⚠️ Bağlantı Hataları": "warn",
        }
        self.current_filter = mapping.get(selected_label, "all")
        self._populate_tree()

    def _populate_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        visible_idx = 0
        for idx, r in enumerate(self.eval_results):
            status_str, row_kind = row_display(r)

            if self.current_filter != "all" and row_kind != self.current_filter:
                continue

            if row_kind == "pass":
                tag = "pass_even" if (visible_idx % 2 == 0) else "pass_odd"
            else:
                tag = row_kind

            visible_idx += 1
            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                tags=(tag,),
                values=(
                    status_str,
                    r.test_case.id,
                    r.test_case.category,
                    r.test_case.title,
                    r.verdict.reason,
                    f"{r.latency_ms:.0f}",
                ),
            )

    def _on_evaluation_complete(
        self,
        results: list[EvaluationResult],
        elapsed: float,
        target_mode: str,
        judge_model: str,
    ) -> None:
        self.eval_results = results
        self.last_elapsed = elapsed
        self._run_meta = (target_mode, judge_model)
        self.active_cancel_event = None
        self.run_btn.configure(state="normal", text="▶️ Denetimi Başlat")
        self.stop_btn.configure(state="disabled")

        summary = self._update_kpis(results)
        evaluated = summary.evaluated
        failed = summary.violated
        review_n = sum(1 for r in results if r.needs_review)
        self.status_label.configure(
            text=f"Tamamlandı ({elapsed:.1f} sn | {summary.total} Test)"
            + (f" | 🔎 {review_n} sonuç elle inceleme bekliyor" if review_n else "")
        )

        self._populate_tree()

        if summary.errors > 0 and evaluated == 0:
            self.mascot_mood = "alert"
            self.bubble_title = "⚠️ HEDEF SUNUCUYA BAĞLANILAMADI (DEVRE KESİCİ AKTİF)"
            self.bubble_text = (
                "İlk 4 istekte hedef sunucu yanıt vermediği için zaman kaybetmemen adına "
                "devre kesici kalan testleri otomatik durdurdu! Satıra tıklayıp ağ hatasını görebilirsin."
            )
        elif failed > 0:
            self.mascot_mood = "alert"
            self.bubble_title = f"🚨 DİKKAT! {failed} ADET GÜVENLİK İHLALİ YAKALADIM!"
            self.bubble_text = (
                f"Değerlendirilen {evaluated} testin {failed} tanesinde güvenlik ihlali tespit ettim! "
                "Kırmızı '🚨 İHLAL' satırlarına tıklarsan hakemin açıklamasını burada anlatırım."
            )
        else:
            self.mascot_mood = "happy"
            self.bubble_title = "✅ HARİKA! TÜM TESTLER GÜVENLİ GEÇTİ!"
            self.bubble_text = f"Değerlendirilen {evaluated} senaryonun tamamında hedef model güvenlik sınırlarını korudu!"

        md_text = generate_markdown_report(results, target_mode, judge_model, elapsed)
        self.report_box.delete("0.0", "end")
        self.report_box.insert("0.0", md_text)

    def _on_row_select(self, _event: object) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        if 0 <= idx < len(self.eval_results):
            self.selected_idx = idx
            r = self.eval_results[idx]
            _, row_kind = row_display(r)
            if row_kind == "warn":
                self.mascot_mood = "alert"
                self.bubble_title = f"⚠️ [{r.test_case.id}] BAĞLANTI HATASI AÇIKLAMASI:"
                self.bubble_text = f"“{r.verdict.reason}”"
            elif row_kind == "fail":
                self.mascot_mood = "alert"
                self.bubble_title = f"🚨 [{r.test_case.id}] HAKEM İHLAL AÇIKLAMASI ({r.verdict.evaluation_method}):"
                self.bubble_text = f"“{r.verdict.reason}”\n(Kategori: {r.test_case.category})"
            else:
                self.mascot_mood = "happy"
                self.bubble_title = f"✅ [{r.test_case.id}] HAKEM ONAYI ({r.verdict.evaluation_method}):"
                self.bubble_text = f"“{r.verdict.reason}”\n(Beklenen: {r.test_case.expected_behavior})"

            reply_body = r.target_response.strip() or "(Hedef sunucudan yanıt alınamadı / Bağlantı hatası)"
            detail = (
                f"📌 TEST: [{r.test_case.id}] {r.test_case.title}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📤 GÖNDERİLEN SORU (PROMPT):\n{r.test_case.prompt}\n\n"
                f"🤖 HEDEF YAPAY ZEKANIN CEVABI:\n{reply_body}"
            )
            self.detail_box.delete("0.0", "end")
            self.detail_box.insert("0.0", detail)
            self._draw_mascot_scene()

    def _change_font_scale(self, delta: float) -> None:
        """Tablo, soru/cevap kutusu, rapor ve konuşma balonundaki yazıyı büyütür/küçültür."""
        self.font_scale = max(0.8, min(2.2, round(self.font_scale + delta, 2)))
        sc = self.font_scale
        style = ttk.Style()
        style.configure("Treeview", font=("Consolas", max(8, int(10 * sc))), rowheight=int(29 * sc))
        style.configure("Treeview.Heading", font=("Consolas", max(8, int(10 * sc)), "bold"))
        self.detail_box.configure(font=ctk.CTkFont(family="Consolas", size=max(9, int(13 * sc))))
        self.report_box.configure(font=ctk.CTkFont(family="Consolas", size=max(9, int(12 * sc))))
        self._draw_mascot_scene()

    def _visible_indices(self) -> list[int]:
        return [int(i) for i in self.tree.get_children()] or list(range(len(self.eval_results)))

    def _open_detail(self) -> None:
        """Seçili (yoksa son) sonucun tüm ayrıntısını büyük pencerede açar."""
        if not self.eval_results:
            messagebox.showinfo("Bilgi", "Henüz gösterilecek sonuç yok. Önce denetimi çalıştırın veya '📂 Sonuç Aç' kullanın.")
            return
        indices = self._visible_indices()
        idx = self.selected_idx if self.selected_idx in indices else indices[-1]
        if self._detail_win is not None:
            try:
                self._detail_win.destroy()
            except Exception:
                pass
        self._detail_win = ResultDetailWindow(
            self, self.eval_results, indices, indices.index(idx), THEME,
            font_scale=self.font_scale, on_change=self._on_manual_change,
        )

    def _refresh_report(self) -> None:
        mode, judge = self._run_meta
        md_text = generate_markdown_report(self.eval_results, mode, judge, self.last_elapsed)
        self.report_box.delete("0.0", "end")
        self.report_box.insert("0.0", md_text)

    def _on_manual_change(self, idx: int) -> None:
        """Elle karar/not değişince tablo, KPI ve rapor güncellenir."""
        self._update_kpis(self.eval_results)
        keep = self.selected_idx
        self._populate_tree()
        if keep is not None and self.tree.exists(str(keep)):
            self.tree.selection_set(str(keep))
        self._refresh_report()

    def _autosave_result(self, res: EvaluationResult) -> None:
        """Uzun denetimler yarıda kesilirse sonuçlar kaybolmasın diye her sonucu diske yazar."""
        try:
            self._autosave_path.parent.mkdir(parents=True, exist_ok=True)
            with self._autosave_path.open("a", encoding="utf-8") as f:
                f.write(res.model_dump_json() + "\n")
        except OSError:
            pass

    def _load_results_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Önceki denetim sonucunu aç",
            initialdir=str(self._autosave_path.parent) if self._autosave_path.parent.exists() else None,
            filetypes=[("Sonuç dosyaları", "*.json *.jsonl"), ("Tümü", "*.*")],
        )
        if not path:
            return
        try:
            raw = Path(path).read_text(encoding="utf-8").strip()
            if raw.startswith("["):
                rows = json.loads(raw)
            else:
                rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            loaded = [EvaluationResult.model_validate(r) for r in rows]
        except Exception as exc:
            messagebox.showerror("Açılamadı", f"Dosya sonuç biçiminde değil:\n{exc}")
            return
        self.eval_results = loaded
        self.selected_idx = None
        self._run_meta = ("yüklenen dosya", Path(path).name)
        self._update_kpis(loaded)
        self._populate_tree()
        self._refresh_report()
        review_n = sum(1 for r in loaded if r.needs_review)
        self.status_label.configure(
            text=f"Yüklendi: {len(loaded)} sonuç" + (f" | 🔎 {review_n} inceleme bekliyor" if review_n else "")
        )
        self.mascot_mood = "idle"
        self.bubble_title = f"📂 {len(loaded)} sonuç yüklendi"
        self.bubble_text = "Bir satıra tıklayıp ayrıntıya bakabilir, 🔎 işaretli kararları elle doğrulayabilirsin."
        self._draw_mascot_scene()

    def _export_markdown_report(self) -> None:
        if not self.eval_results:
            messagebox.showinfo("Bilgi", "Önce denetimi çalıştırın.")
            return
        save_path = filedialog.asksaveasfilename(
            title="Raporu Kaydet",
            defaultextension=".md",
            initialfile="owasp_llm_denetim_raporu.md",
            filetypes=[("Markdown Raporu", "*.md"), ("JSON Sonuçları", "*.json")],
        )
        if not save_path:
            return
        if save_path.endswith(".json"):
            data = json.dumps([r.model_dump() for r in self.eval_results], ensure_ascii=False, indent=2)
            Path(save_path).write_text(data, encoding="utf-8")
        else:
            md_text = self.report_box.get("0.0", "end")
            Path(save_path).write_text(md_text, encoding="utf-8")
        messagebox.showinfo("Kaydedildi", f"Rapor başarıyla kaydedildi:\n{save_path}")
