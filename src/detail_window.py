"""Tek bir denetim sonucunun tüm ayrıntısını büyük ve okunaklı gösteren pencere.

Konuşma balonuna tıklayınca, tablodan çift tıklayınca veya "Detay" düğmesiyle açılır.
Önceki/Sonraki ile tablodaki sıraya göre gezilir; elle karar (yanlış pozitif / gerçek ihlal) verilebilir.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional

import customtkinter as ctk

from src.models import EvaluationResult

_STATUS = {
    "passed": ("✅ GÜVENLİ", "pass"),
    "violated": ("🚨 İHLAL", "fail"),
    "error": ("⚠️ BELİRSİZ / HATA", "warn"),
    "cancelled": ("⏹️ İPTAL", "warn"),
}


class ResultDetailWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent: tk.Misc,
        results: List[EvaluationResult],
        indices: List[int],
        start_pos: int,
        theme: Dict[str, str],
        font_scale: float = 1.0,
        on_change: Optional[Callable[[int], None]] = None,
    ) -> None:
        super().__init__(parent, fg_color=theme["bg_main"])
        self.results = results
        self.indices = indices
        self.pos = max(0, min(start_pos, len(indices) - 1))
        self.theme = theme
        self.scale = font_scale
        self.on_change = on_change

        self.title("🔍 Test Ayrıntısı")
        self.geometry("1000x780")
        self.minsize(760, 560)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- Üst bilgi şeridi ---
        self.head = ctk.CTkFrame(self, fg_color=theme["bg_panel"], corner_radius=8)
        self.head.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        self.head.grid_columnconfigure(0, weight=1)
        self.lbl_title = ctk.CTkLabel(
            self.head, text="", anchor="w", justify="left", wraplength=820,
            font=ctk.CTkFont(family="Segoe UI", size=int(18 * self.scale), weight="bold"),
        )
        self.lbl_title.grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))
        self.lbl_meta = ctk.CTkLabel(
            self.head, text="", anchor="w", justify="left", wraplength=820, text_color=theme["text_dim"],
            font=ctk.CTkFont(family="Consolas", size=int(12 * self.scale)),
        )
        self.lbl_meta.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        nav = ctk.CTkFrame(self.head, fg_color="transparent")
        nav.grid(row=0, column=1, rowspan=2, padx=8)
        ctk.CTkButton(nav, text="◀", width=36, command=self.prev, fg_color=theme["accent"]).pack(side="left", padx=2)
        self.lbl_pos = ctk.CTkLabel(nav, text="", width=70)
        self.lbl_pos.pack(side="left")
        ctk.CTkButton(nav, text="▶", width=36, command=self.next, fg_color=theme["accent"]).pack(side="left", padx=2)
        ctk.CTkButton(nav, text="A−", width=36, command=lambda: self.change_scale(-0.1),
                      fg_color=theme["bg_card"]).pack(side="left", padx=(12, 2))
        ctk.CTkButton(nav, text="A+", width=36, command=lambda: self.change_scale(0.1),
                      fg_color=theme["bg_card"]).pack(side="left", padx=2)

        # --- Elle karar çubuğu ---
        tri = ctk.CTkFrame(self, fg_color=theme["bg_card"], corner_radius=8)
        tri.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        tri.grid_columnconfigure(4, weight=1)
        ctk.CTkLabel(tri, text="Elle karar:", text_color=theme["text_dim"]).grid(row=0, column=0, padx=(10, 6), pady=8)
        ctk.CTkButton(tri, text="🚨 Gerçek ihlal", width=120, fg_color="#7F1D1D", hover_color="#991B1B",
                      command=lambda: self.set_manual("violated")).grid(row=0, column=1, padx=3)
        ctk.CTkButton(tri, text="✅ Yanlış pozitif / güvenli", width=170, fg_color="#14532D", hover_color="#166534",
                      command=lambda: self.set_manual("passed")).grid(row=0, column=2, padx=3)
        ctk.CTkButton(tri, text="↩ Geri al", width=80, fg_color=theme["border"],
                      command=lambda: self.set_manual(None)).grid(row=0, column=3, padx=3)
        self.note_entry = ctk.CTkEntry(tri, placeholder_text="Not (rapora yazılır)...", fg_color=theme["bg_input"])
        self.note_entry.grid(row=0, column=4, sticky="ew", padx=8, pady=8)
        self.note_entry.bind("<FocusOut>", lambda _e: self._save_note())
        self.note_entry.bind("<Return>", lambda _e: self._save_note())

        # --- Ana metin alanı ---
        body = ctk.CTkFrame(self, fg_color=theme["bg_input"], corner_radius=8)
        body.grid(row=2, column=0, sticky="nsew", padx=10, pady=4)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.text = tk.Text(
            body, wrap="word", bg=theme["bg_input"], fg=theme["text_main"], insertbackground=theme["text_main"],
            relief="flat", padx=14, pady=10, borderwidth=0, spacing1=2, spacing3=2,
        )
        sb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        # --- Alt düğmeler ---
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=10, pady=(4, 10))
        for label, cmd in (
            ("📋 Soruyu kopyala", lambda: self._copy("prompt")),
            ("📋 Cevabı kopyala", lambda: self._copy("reply")),
            ("📋 Hepsini kopyala", lambda: self._copy("all")),
        ):
            ctk.CTkButton(foot, text=label, command=cmd, fg_color=theme["secondary"], text_color="#141118",
                          width=150).pack(side="left", padx=3)
        ctk.CTkButton(foot, text="Kapat (Esc)", command=self.destroy, fg_color=theme["border"],
                      width=110).pack(side="right", padx=3)

        self.bind("<Left>", lambda _e: self.prev())
        self.bind("<Right>", lambda _e: self.next())
        self.bind("<Escape>", lambda _e: self.destroy())
        self._configure_tags()
        self.render()
        self.after(150, self.lift)
        self.after(200, self.focus_force)

    # -- yardımcılar --
    @property
    def res(self) -> EvaluationResult:
        return self.results[self.indices[self.pos]]

    def _configure_tags(self) -> None:
        t, th = self.text, self.theme
        base = int(13 * self.scale)
        t.configure(font=("Segoe UI", base))
        t.tag_configure("h", font=("Segoe UI", base + 1, "bold"), foreground=th["secondary"], spacing1=12)
        t.tag_configure("box", font=("Consolas", base), background=th["bg_card"], lmargin1=10, lmargin2=10,
                        rmargin=10, spacing1=4, spacing3=4)
        t.tag_configure("hit", background="#7F1D1D", foreground="#FFFFFF")
        t.tag_configure("pass", foreground=th["pass"])
        t.tag_configure("fail", foreground=th["fail"])
        t.tag_configure("warn", foreground=th["warn"])
        t.tag_configure("dim", foreground=th["text_dim"])

    def change_scale(self, delta: float) -> None:
        self.scale = max(0.8, min(2.2, round(self.scale + delta, 2)))
        self.lbl_title.configure(font=ctk.CTkFont(family="Segoe UI", size=int(18 * self.scale), weight="bold"))
        self.lbl_meta.configure(font=ctk.CTkFont(family="Consolas", size=int(12 * self.scale)))
        self._configure_tags()
        self.render()

    def prev(self) -> None:
        if self.pos > 0:
            self._save_note()
            self.pos -= 1
            self.render()

    def next(self) -> None:
        if self.pos < len(self.indices) - 1:
            self._save_note()
            self.pos += 1
            self.render()

    def _insert_box(self, content: str, hits: Optional[List[str]] = None) -> None:
        start = self.text.index("end-1c")
        self.text.insert("end", content + "\n", "box")
        for kw in hits or []:
            if not kw:
                continue
            idx = start
            while True:
                idx = self.text.search(kw, idx, stopindex="end", nocase=True)
                if not idx:
                    break
                end = f"{idx}+{len(kw)}c"
                self.text.tag_add("hit", idx, end)
                idx = end

    def render(self) -> None:
        r = self.res
        v = r.verdict
        outcome = r.effective_outcome
        label, kind = _STATUS[outcome]
        manual = " (elle karar)" if r.manual_outcome else ""
        self.lbl_title.configure(text=f"{label}{manual}   [{r.test_case.id}] {r.test_case.title}")
        review = "   🔎 elle doğrulanması önerilir" if r.needs_review else ""
        self.lbl_meta.configure(
            text=f"{r.test_case.category}   |   yöntem: {v.evaluation_method}   |   güven: {v.confidence:.2f}   |   "
                 f"{r.latency_ms:.0f} ms{review}"
        )
        self.lbl_pos.configure(text=f"{self.pos + 1} / {len(self.indices)}")
        self.note_entry.delete(0, "end")
        if r.manual_note:
            self.note_entry.insert(0, r.manual_note)

        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "HAKEM KARARI VE GEREKÇESİ\n", "h")
        self.text.insert("end", f"{v.reason}\n", kind)
        if r.manual_outcome and r.manual_outcome != v.outcome:
            self.text.insert("end", f"\n(Otomatik karar: {_STATUS[v.outcome][0]}, elle değiştirildi.)\n", "dim")
        self.text.insert("end", "\nBEKLENEN GÜVENLİ DAVRANIŞ\n", "h")
        self.text.insert("end", f"{r.test_case.expected_behavior}\n")
        if r.test_case.forbidden_keywords:
            self.text.insert("end", "\nYASAKLI İFADELER (yanıtta kırmızı işaretlenir)\n", "h")
            self.text.insert("end", ", ".join(r.test_case.forbidden_keywords) + "\n", "dim")
        self.text.insert("end", "\n📤 GÖNDERİLEN SORU (PROMPT)\n", "h")
        self._insert_box(r.test_case.prompt, r.test_case.forbidden_keywords)
        self.text.insert("end", "\n🤖 HEDEF YAPAY ZEKANIN CEVABI\n", "h")
        reply = r.target_response.strip() or "(Yanıt alınamadı)"
        self._insert_box(reply, r.test_case.forbidden_keywords)
        if r.error:
            self.text.insert("end", f"\nBağlantı hatası: {r.error}\n", "warn")
        self.text.configure(state="disabled")
        self.text.yview_moveto(0)

    def _save_note(self) -> None:
        r = self.res
        note = self.note_entry.get().strip()
        if note != r.manual_note:
            r.manual_note = note
            if self.on_change:
                self.on_change(self.indices[self.pos])

    def set_manual(self, outcome: Optional[str]) -> None:
        r = self.res
        r.manual_outcome = outcome  # type: ignore[assignment]
        r.manual_note = self.note_entry.get().strip()
        if self.on_change:
            self.on_change(self.indices[self.pos])
        self.render()

    def _copy(self, what: str) -> None:
        r = self.res
        if what == "prompt":
            data = r.test_case.prompt
        elif what == "reply":
            data = r.target_response
        else:
            data = (
                f"[{r.test_case.id}] {r.test_case.title}\nKategori: {r.test_case.category}\n"
                f"Karar: {_STATUS[r.effective_outcome][0]} ({r.verdict.evaluation_method})\n"
                f"Gerekçe: {r.verdict.reason}\n\nPROMPT:\n{r.test_case.prompt}\n\nCEVAP:\n{r.target_response}\n"
            )
        self.clipboard_clear()
        self.clipboard_append(data)
