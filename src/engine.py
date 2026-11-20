import asyncio
from typing import Callable, List, Optional
import httpx
from src.evaluators import evaluate_response
from src.models import EvaluationResult, JudgeConfig, JudgeVerdict, TargetConfig, TestCase
from src.target_client import query_target


def _cancelled_result(test_case: TestCase) -> EvaluationResult:
    return EvaluationResult(
        test_case=test_case,
        target_response="",
        latency_ms=0.0,
        verdict=JudgeVerdict(
            outcome="cancelled",
            confidence=0.0,
            reason="Denetim kullanıcı veya devre kesici tarafından durduruldu.",
            evaluation_method="cancelled",
        ),
        error="cancelled",
    )


def _is_target_failure(res: EvaluationResult) -> bool:
    """Hedefe ulaşılamadı mı (sorgu istisna fırlattı)? Devre kesici yalnızca bunları sayar.

    Boş yanıt gibi değerlendirme hataları da 'error' sonucudur ama error alanı boştur.
    """
    return res.verdict.outcome == "error" and res.error is not None


async def run_single_test(
    test_case: TestCase,
    target_config: TargetConfig,
    judge_config: JudgeConfig,
    semaphore: asyncio.Semaphore,
    rate_limit_delay: float = 0.0,
    http_client: Optional[httpx.AsyncClient] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> EvaluationResult:
    """Tek bir test senaryosunu semafor, iptal sinyali ve paylaşımlı HTTP havuzu altında çalıştırır."""
    if cancel_event and cancel_event.is_set():
        return _cancelled_result(test_case)

    async with semaphore:
        if cancel_event and cancel_event.is_set():
            return _cancelled_result(test_case)

        if rate_limit_delay > 0:
            await asyncio.sleep(rate_limit_delay)

        try:
            target_reply, latency_ms = await query_target(
                test_case.prompt, target_config, http_client=http_client
            )
            verdict = await evaluate_response(
                test_case, target_reply, judge_config, http_client=http_client
            )
            return EvaluationResult(
                test_case=test_case,
                target_response=target_reply,
                latency_ms=latency_ms,
                verdict=verdict,
            )
        except Exception as exc:
            err_detail = str(exc).strip() or type(exc).__name__
            return EvaluationResult(
                test_case=test_case,
                target_response="",
                latency_ms=0.0,
                verdict=JudgeVerdict(
                    outcome="error",
                    confidence=0.0,
                    reason=f"Hedef bağlantı hatası: {err_detail}",
                    evaluation_method="connection_error",
                ),
                error=err_detail,
            )


async def run_test_suite(
    test_cases: List[TestCase],
    target_config: TargetConfig,
    judge_config: JudgeConfig,
    concurrency: int = 3,
    rate_limit_delay: float = 0.2,
    on_progress: Optional[Callable[[int, int, "EvaluationResult"], None]] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> List[EvaluationResult]:
    """Tüm test veri setini paylaşımlı bağlantı havuzu ve devre kesici (circuit-breaker) ile çalıştırır."""
    effective_concurrency = 1 if target_config.mode == "browser_bridge" else max(1, concurrency)
    semaphore = asyncio.Semaphore(effective_concurrency)
    total = len(test_cases)
    completed = 0
    consecutive_conn_errors = 0
    has_any_success = False
    internal_cancel = cancel_event or asyncio.Event()

    limits = httpx.Limits(max_connections=max(10, concurrency * 4), max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits, timeout=28.0, follow_redirects=True) as shared_client:

        async def _wrapped(tc: TestCase) -> EvaluationResult:
            nonlocal completed, consecutive_conn_errors, has_any_success
            res = await run_single_test(
                tc,
                target_config,
                judge_config,
                semaphore,
                rate_limit_delay,
                http_client=shared_client,
                cancel_event=internal_cancel,
            )
            if _is_target_failure(res):
                consecutive_conn_errors += 1
                # Henüz hiçbir test başarılı olmadıysa 4 hatada, daha önce çalışan oturumda ise 10 ardışık hatada durdur
                threshold = 10 if has_any_success else 4
                if consecutive_conn_errors >= threshold:
                    internal_cancel.set()
            elif res.verdict.outcome != "cancelled":
                consecutive_conn_errors = 0
                has_any_success = True

            completed += 1
            if on_progress and res.verdict.outcome != "cancelled":
                on_progress(completed, total, res)
            return res

        tasks = [_wrapped(tc) for tc in test_cases]
        raw_results = await asyncio.gather(*tasks)
        # İptal edilen (çalıştırılmayan) boş kayıtları filtrele
        return [r for r in raw_results if r.verdict.outcome != "cancelled"]
