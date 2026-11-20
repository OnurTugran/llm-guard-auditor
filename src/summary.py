"""Denetim sonuçlarının özet istatistikleri.

Geçen / ihlal / hata sayıları ve uyumluluk skoru yalnızca burada hesaplanır;
raporlayıcı, masaüstü ve web arayüzü bu modülü kullanır.
"""
from dataclasses import dataclass, field
from typing import Dict, Iterable

from src.models import EvaluationResult


def _rate(passed: int, violated: int) -> float:
    evaluated = passed + violated
    return round((passed / evaluated) * 100, 1) if evaluated > 0 else 0.0


@dataclass
class CategoryStats:
    total: int = 0
    passed: int = 0
    violated: int = 0
    errors: int = 0

    @property
    def compliance_rate(self) -> float:
        return _rate(self.passed, self.violated)


@dataclass
class AuditSummary:
    total: int = 0
    passed: int = 0
    violated: int = 0
    errors: int = 0
    judge_fallbacks: int = 0
    """Hakem API'sine ulaşılamadığı için yerel denetçiye düşen değerlendirme sayısı."""
    by_category: Dict[str, CategoryStats] = field(default_factory=dict)

    @property
    def evaluated(self) -> int:
        """Skora dahil edilen (gerçekten değerlendirilen) test sayısı; hatalar hariç."""
        return self.passed + self.violated

    @property
    def compliance_rate(self) -> float:
        """Uyumluluk skoru (%). Hatalar ne geçen ne ihlal sayılır."""
        return _rate(self.passed, self.violated)


def summarize(results: Iterable[EvaluationResult]) -> AuditSummary:
    """Sonuç listesinden özet istatistikleri üretir. İptal edilen testler sayılmaz."""
    summary = AuditSummary()
    for r in results:
        outcome = r.effective_outcome
        if outcome == "cancelled":
            continue
        cat = summary.by_category.setdefault(r.test_case.category, CategoryStats())
        summary.total += 1
        cat.total += 1
        if outcome == "passed":
            summary.passed += 1
            cat.passed += 1
        elif outcome == "violated":
            summary.violated += 1
            cat.violated += 1
        else:
            summary.errors += 1
            cat.errors += 1
        if r.verdict.evaluation_method == "judge_fallback":
            summary.judge_fallbacks += 1
    return summary
