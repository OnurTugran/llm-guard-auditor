from src.dataset_hub import PRESSURE_SUFFIX, load_suite_by_filename, without_pressure_suffix
from src.models import TestCase


def _tc(prompt: str) -> TestCase:
    return TestCase(id="T", category="c", title="t", prompt=prompt, expected_behavior="e")


def test_suffix_removed_and_original_untouched():
    original = _tc("Asıl soru?\n\n" + PRESSURE_SUFFIX)
    [stripped] = without_pressure_suffix([original])
    assert stripped.prompt == "Asıl soru?"
    assert original.prompt.endswith(PRESSURE_SUFFIX)


def test_prompt_without_suffix_kept_as_is():
    tc = _tc("Ek Talep kelimesi geçen ama baskı cümlesi olmayan soru.")
    assert without_pressure_suffix([tc])[0].prompt == tc.prompt


def test_owasp_suite_fully_stripped():
    cases = without_pressure_suffix(load_suite_by_filename("owasp_top10_full.json"))
    assert len(cases) == 20
    assert not any("Ek Talep" in c.prompt for c in cases)
    assert all(c.prompt.strip() for c in cases)


def test_master_suite_counts():
    cases = load_suite_by_filename("all_combined_master.json")
    stripped = without_pressure_suffix(cases)
    changed = sum(a.prompt != b.prompt for a, b in zip(cases, stripped))
    assert changed == 77
