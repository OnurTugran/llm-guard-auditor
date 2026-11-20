from src.models import EvaluationResult, JudgeVerdict, TestCase
from src.reporter import generate_markdown_report
from src.summary import summarize


def _result(outcome: str, category: str = "LLM01", method: str = "rule_based", idx: int = 0) -> EvaluationResult:
    return EvaluationResult(
        test_case=TestCase(
            id=f"T-{idx}",
            category=category,
            title=f"Test {idx}",
            prompt="p",
            expected_behavior="e",
        ),
        target_response="yanıt",
        latency_ms=1.0,
        verdict=JudgeVerdict(outcome=outcome, reason="r", evaluation_method=method),
        error="boom" if outcome == "error" else None,
    )


def test_errors_are_excluded_from_score():
    s = summarize([_result("passed"), _result("violated"), _result("error"), _result("error")])
    assert (s.total, s.passed, s.violated, s.errors) == (4, 1, 1, 2)
    assert s.evaluated == 2
    assert s.compliance_rate == 50.0


def test_cancelled_results_are_not_counted():
    s = summarize([_result("passed"), _result("cancelled")])
    assert s.total == 1
    assert s.compliance_rate == 100.0


def test_empty_and_all_errors_give_zero_score():
    assert summarize([]).compliance_rate == 0.0
    assert summarize([_result("error")]).compliance_rate == 0.0


def test_judge_fallbacks_counted_regardless_of_outcome():
    s = summarize([
        _result("passed", method="judge_fallback"),
        _result("violated", method="judge_fallback"),
        _result("passed", method="heuristic_local"),
    ])
    assert s.judge_fallbacks == 2


def test_by_category():
    s = summarize([
        _result("passed", "LLM01"),
        _result("violated", "LLM01"),
        _result("error", "LLM02"),
    ])
    assert s.by_category["LLM01"].compliance_rate == 50.0
    assert s.by_category["LLM02"].errors == 1
    assert s.by_category["LLM02"].compliance_rate == 0.0


def test_compliant_property_kept_for_exports():
    v = JudgeVerdict(outcome="passed", reason="r")
    assert v.compliant is True
    assert v.model_dump()["compliant"] is True
    assert JudgeVerdict(outcome="error", reason="r").compliant is False


def test_report_lists_only_violations_as_poc():
    md = generate_markdown_report(
        [_result("violated", idx=1), _result("error", idx=2), _result("passed", idx=3)],
        target_mode="demo_sandbox",
        judge_model="x",
        elapsed_seconds=1.0,
    )
    poc = md.split("## 2.")[1]
    assert "[T-1]" in poc
    assert "[T-2]" not in poc
    # Hata skora girmez: 1 güvenli / 1 ihlal -> %50
    assert "**%50.0** (1 Güvenli / 1 İhlal)" in md
    assert "1 Hata / Yanıtsız" in md
