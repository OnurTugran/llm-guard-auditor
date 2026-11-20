from datetime import datetime
from typing import List
from src.models import EvaluationResult
from src.summary import summarize


def generate_markdown_report(
    results: List[EvaluationResult],
    target_mode: str,
    judge_model: str,
    elapsed_seconds: float,
) -> str:
    """Kurumsal OWASP LLM Güvenlik ve Uyumluluk Denetim Raporu (Markdown formatında) üretir."""
    s = summarize(results)

    lines = [
        "# Kurumsal Yapay Zeka Güvenlik ve Uyumluluk Raporu (OWASP LLM Top 10)",
        "",
        f"- **Rapor Tarihi:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Hedef Sistem Modu:** `{target_mode}`",
        f"- **Değerlendirici Hakem Model:** `{judge_model}`",
        f"- **Tamamlanan Test Senaryosu:** {s.total} ({s.evaluated} Değerlendirildi, {s.errors} Hata / Yanıtsız)",
        f"- **Yerel Yedek Denetçiye Düşen Değerlendirme:** {s.judge_fallbacks} (Hakem API'sine ulaşılamadı, sonuçlar kural tabanlıdır)",
        f"- **Toplam Süre:** {elapsed_seconds:.2f} sn",
        f"- **Genel Güvenlik Uyumluluk Skoru:** **%{s.compliance_rate}** ({s.passed} Güvenli / {s.violated} İhlal)",
        "",
        "---",
        "",
        "## 1. OWASP Kategorilerine Göre Dağılım",
        "",
        "| OWASP Kategorisi | Toplam Test | Güvenli (Pass) | İhlal (Fail) | Hata / Yanıtsız | Uyumluluk Oranı |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    for cat, st in s.by_category.items():
        lines.append(
            f"| {cat} | {st.total} | {st.passed} | {st.violated} | {st.errors} | %{st.compliance_rate} |"
        )

    lines.extend(["", "---", "", "## 2. Tespit Edilen Uyumsuzluklar ve Kanıtlar (PoC)", ""])

    violations = [r for r in results if r.effective_outcome == "violated"]
    if not violations:
        lines.append("Tüm test senaryoları güvenlik sınırları içerisinde başarıyla tamamlanmıştır.")
    else:
        for idx, v in enumerate(violations, start=1):
            lines.extend(
                [
                    f"### {idx}. [{v.test_case.id}] {v.test_case.title}",
                    f"- **Kategori:** {v.test_case.category}",
                    f"- **Değerlendirme Yöntemi:** `{v.verdict.evaluation_method}` (Güven: {v.verdict.confidence})",
                    f"- **Hakem Bulgusu:** {v.verdict.reason}",
                    f"- **Doğrulama:** {'✅ Elle doğrulandı' if v.manual_outcome == 'violated' else '🔎 Otomatik karar, elle doğrulanmadı (rapora koymadan önce kontrol edin)' if v.needs_review else 'Hakem kararı'}",
                    *([f"- **Not:** {v.manual_note}"] if v.manual_note else []),
                    f"- **Gönderilen Girdi (Prompt):**",
                    f"  > {v.test_case.prompt}",
                    f"- **Hedef Modelin Yanıtı (Kanıt):**",
                    f"  > {v.target_response}",
                    "",
                ]
            )

    return "\n".join(lines)
