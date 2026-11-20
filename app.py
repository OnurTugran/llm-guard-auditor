import asyncio
import json
import time
from pathlib import Path
from typing import List
import pandas as pd
import streamlit as st

from src.dataset_hub import (
    SUITE_CATALOG,
    fetch_huggingface_dataset_rows,
    load_suite_by_filename,
    without_pressure_suffix,
)
from src.engine import run_test_suite
from src.models import EvaluationResult, JudgeConfig, TargetConfig, TestCase
from src.reporter import generate_markdown_report
from src.summary import summarize

_STATUS_LABELS = {
    "passed": "✅ GÜVENLİ",
    "violated": "🚨 İHLAL",
    "error": "⚠️ HATA",
    "cancelled": "⏹️ İPTAL",
}

st.set_page_config(
    page_title="LLM Guardrail & OWASP Denetim Platformu",
    page_icon="🛡️",
    layout="wide",
)

DEFAULT_DATASET_PATH = Path(__file__).parent / "datasets" / "all_combined_master.json"


def load_default_cases() -> List[TestCase]:
    if DEFAULT_DATASET_PATH.exists():
        raw = json.loads(DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
        return [TestCase(**item) for item in raw]
    return []


DEFAULT_CASE_COUNT = len(load_default_cases())


if "test_cases" not in st.session_state:
    st.session_state.test_cases = load_default_cases()

if "eval_results" not in st.session_state:
    st.session_state.eval_results = []

if "last_elapsed" not in st.session_state:
    st.session_state.last_elapsed = 0.0

# --- SIDEBAR: HAKEM & HEDEF AYARLARI ---
with st.sidebar:
    st.header("⚖️ 1. Hakem Model (LLM-as-a-Judge)")
    judge_provider = st.selectbox(
        "Hakem Sağlayıcısı Seçin",
        options=["gemini", "anthropic", "openai", "xai", "groq", "rule_only"],
        format_func=lambda x: {
            "gemini": "Google Gemini (Önerilen)",
            "anthropic": "Anthropic Claude",
            "openai": "OpenAI GPT",
            "xai": "xAI Grok (Grok-2 / Grok-3)",
            "groq": "Groq Cloud (Llama 3 - Ultra Hızlı Çıkarım)",
            "rule_only": "Sadece Kural/Kelime Kontrolü (API Keysiz)",
        }[x],
    )

    provider_models = {
        "gemini": [
            "gemini/gemini-3.8-flash",
            "gemini/gemini-3.6-flash",
            "gemini/gemini-3.5-flash-lite",
            "gemini/gemini-3.1-pro-preview",
            "gemini/gemini-2.5-pro",
            "gemini/gemini-2.5-flash",
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

    if judge_provider != "rule_only":
        model_choices = provider_models[judge_provider] + ["➕ Özel Model Adı Gir..."]
        selected_judge_model = st.selectbox(
            "Hakem Model Seçin",
            options=model_choices,
        )
        if selected_judge_model == "➕ Özel Model Adı Gir...":
            judge_model_name = st.text_input(
                "Özel Hakem Model Adı (LiteLLM formatı)",
                value=provider_models[judge_provider][0],
            )
        else:
            judge_model_name = selected_judge_model

        judge_api_key = st.text_input(
            f"{judge_provider.upper()} API Anahtarı",
            type="password",
            help="Kendi Claude, Gemini, OpenAI, Grok veya Groq API anahtarınızı girin.",
        )
    else:
        judge_model_name = "rule_only"
        judge_api_key = ""

    st.divider()
    st.header("🎯 2. Test Edilecek Hedef Sistem")
    target_mode = st.selectbox(
        "Hedef Bağlantı Modu",
        options=["demo_sandbox", "custom_http", "openai_compatible"],
        format_func=lambda x: {
            "demo_sandbox": "1. Dahili Demo Simülatör (Hemen Test Et)",
            "custom_http": "2. Web Chat API Uç Noktası (Custom HTTP / Bug Bounty)",
            "openai_compatible": "3. Standart LLM API (OpenAI Uyumlu)",
        }[x],
    )

    target_cfg = TargetConfig(mode=target_mode)

    if target_mode == "demo_sandbox":
        st.caption(
            "Harici bir sunucuya ihtiyaç duymadan aracın nasıl çalıştığını test etmeniz için dahili simülatör."
        )
        target_cfg.sandbox_strict_guardrails = st.toggle(
            "Güçlü Güvenlik Filtresini Aktif Et (Guardrail Açık)",
            value=False,
            help="Kapalıyken simülatör bilerek açık verir, açıkken tüm ihlalleri engeller.",
        )
    elif target_mode == "custom_http":
        st.caption(
            "Tarayıcı Geliştirici Araçları (Network) sekmesinden aldığınız Web Chat API bilgilerini girin."
        )
        target_cfg.endpoint_url = st.text_input(
            "Hedef Chat API URL",
            placeholder="https://ornek-uygulama.com/api/chat",
        )
        raw_headers = st.text_area(
            "Özel Başlıklar / Cookie (JSON)",
            value='{\n  "Authorization": "Bearer TOKEN_BURAYA"\n}',
            height=100,
        )
        try:
            target_cfg.custom_headers = json.loads(raw_headers)
        except Exception:
            st.warning("Header JSON formatı geçersiz, varsayılan boş kullanılacak.")
            target_cfg.custom_headers = {}

        target_cfg.payload_template = st.text_area(
            "İstek Gövdesi Şablonu ({{prompt}} otomatik değiştirilir)",
            value='{"message": "{{prompt}}"}',
            height=80,
        )
        target_cfg.response_json_field = st.text_input(
            "Yanıt JSON Alan Yolu (Örn: reply veya data.message)",
            value="reply",
        )
    elif target_mode == "openai_compatible":
        target_cfg.endpoint_url = st.text_input(
            "Base URL (Opsiyonel)",
            placeholder="https://api.openai.com/v1",
        )
        target_model_opts = [
            "openai/gpt-4o-mini",
            "openai/gpt-4o",
            "gemini/gemini-3.8-flash",
            "gemini/gemini-3.6-flash",
            "gemini/gemini-2.5-flash",
            "anthropic/claude-3-7-sonnet-latest",
            "anthropic/claude-3-5-sonnet-20241022",
            "xai/grok-2-latest",
            "groq/llama-3.3-70b-versatile",
            "➕ Özel Hedef Model Yaz...",
        ]
        sel_target_m = st.selectbox("Hedef Model Seçin", options=target_model_opts)
        if sel_target_m == "➕ Özel Hedef Model Yaz...":
            target_cfg.model_name = st.text_input("Özel Hedef Model Adı", value="gpt-4o-mini")
        else:
            target_cfg.model_name = sel_target_m
        target_cfg.api_key = st.text_input(
            "Hedef API Anahtarı",
            type="password",
        )
        target_cfg.system_prompt = st.text_area(
            "Test Edilecek Sistem Komutu (System Prompt)",
            value=target_cfg.system_prompt,
        )

    st.divider()
    st.header("⚡ 3. Hız Sınırı & Eşzamanlılık")
    concurrency = st.slider(
        "Eşzamanlı İstek Sayısı (Concurrency)",
        min_value=1,
        max_value=10,
        value=3,
    )
    rate_limit_delay = st.slider(
        "İstekler Arası Bekleme (Rate Limit - Saniye)",
        min_value=0.0,
        max_value=5.0,
        value=0.2,
        step=0.1,
        help="Hedef sistemi yormamak (DoS önlemi) için istekler arasına gecikme koyar.",
    )
    send_pressure_suffix = st.toggle(
        "'Ek Talep' baskı cümlesini gönder",
        value=True,
        help=(
            "Kapalıyken soruların sonundaki 'güvenlik uyarılarını atla, kısıtlamasız mod' cümlesi "
            "gönderilmez; böylece kalıp ret yerine asıl saldırıya verilen yanıt ölçülür."
        ),
    )

# --- ANA EKRAN ---
st.title("🛡️ OWASP LLM Güvenlik ve Uyumluluk Denetim Platformu")
st.markdown(
    "Yapay zeka sohbet uygulamalarını **OWASP LLM Top 10** standartlarına göre asenkron test eden, "
    "**LLM-as-a-Judge** (Hakem Model) ile değerlendiren ve kurumsal denetim raporu üreten çerçeve."
)

tab_run, tab_dataset, tab_report = st.tabs(
    ["🚀 Denetimi Çalıştır & Sonuçlar", "📂 Test Veri Seti Yönetimi (JSON)", "📄 Kurumsal Rapor Çıktısı"]
)

with tab_dataset:
    st.subheader("📚 Hazır Veri Seti Paketleri (OWASP, Hugging Face, NVIDIA Garak, Microsoft PyRIT)")
    col_pkg1, col_pkg2, col_pkg3 = st.columns([2, 1, 1])
    with col_pkg1:
        selected_suite_file = st.selectbox(
            "Kullanılacak Hazır Benchmark Paketi",
            options=list(SUITE_CATALOG.keys()),
            format_func=lambda k: SUITE_CATALOG[k]["name"],
        )
        st.caption(f"**Kaynak:** {SUITE_CATALOG[selected_suite_file]['source']} — {SUITE_CATALOG[selected_suite_file]['description']}")
    with col_pkg2:
        if st.button("📥 Seçili Paketi Yükle", use_container_width=True):
            st.session_state.test_cases = load_suite_by_filename(selected_suite_file)
            st.success(f"{len(st.session_state.test_cases)} senaryo yüklendi!")
            st.rerun()
    with col_pkg3:
        if st.button("🤗 Hugging Face'ten Canlı Çek (+20)", use_container_width=True):
            try:
                hf_cases = asyncio.run(fetch_huggingface_dataset_rows("deepset/prompt-injections", limit=20))
                st.session_state.test_cases.extend(hf_cases)
                st.success(f"Hugging Face'ten {len(hf_cases)} canlı senaryo eklendi!")
                st.rerun()
            except Exception as exc:
                st.error(f"HF API Hatası: {exc}")

    st.divider()
    st.subheader("📂 Kendi JSON Veri Setinizi Yükleyin")
    col_up1, col_up2 = st.columns([2, 1])
    with col_up1:
        uploaded_file = st.file_uploader("Harici JSON Test Veri Seti Yükle", type=["json"])
        if uploaded_file is not None:
            try:
                content = json.loads(uploaded_file.read().decode("utf-8"))
                st.session_state.test_cases = [TestCase(**item) for item in content]
                st.success(f"{len(st.session_state.test_cases)} test senaryosu başarıyla yüklendi!")
            except Exception as e:
                st.error(f"JSON şema hatası: {e}")

    with col_up2:
        if st.button(f"🔄 Tüm Birleşik Sete ({DEFAULT_CASE_COUNT} Senaryo) Sıfırla"):
            st.session_state.test_cases = load_default_cases()
            st.rerun()

    # Mevcut senaryoları tablo olarak göster
    if st.session_state.test_cases:
        df_cases = pd.DataFrame([tc.model_dump() for tc in st.session_state.test_cases])
        st.dataframe(df_cases, use_container_width=True)

    with st.expander("➕ Yeni Test Senaryosu Ekle"):
        with st.form("add_test_case_form"):
            c1, c2 = st.columns(2)
            new_id = c1.text_input("Test ID", value=f"CUSTOM-0{len(st.session_state.test_cases)+1}")
            new_cat = c2.selectbox(
                "OWASP Kategorisi",
                [
                    "LLM01: Directive & Role Adherence",
                    "LLM02: Output Formatting & Sanitization",
                    "LLM06: Sensitive Information Protection",
                    "LLM08: Excessive Agency & Scope Boundary",
                ],
            )
            new_title = st.text_input("Test Başlığı", placeholder="Örn: Yetkisiz Veri Sorgusu")
            new_prompt = st.text_area("Gönderilecek Girdi (Prompt)")
            new_expected = st.text_input(
                "Beklenen Güvenli Davranış (Hakem Kriteri)",
                value="Model gizli veriyi paylaşmamalı ve talebi reddetmelidir.",
            )
            new_keywords = st.text_input(
                "Yasaklı Kelimeler / Canary (Virgülle ayırın, opsiyonel)",
                placeholder="CANARY-9921, GIZLI_KOD",
            )
            submitted = st.form_submit_button("Senaryoyu Listeye Ekle")
            if submitted and new_prompt.strip():
                kw_list = [k.strip() for k in new_keywords.split(",") if k.strip()]
                st.session_state.test_cases.append(
                    TestCase(
                        id=new_id,
                        category=new_cat,
                        title=new_title or "Özel Test",
                        prompt=new_prompt,
                        expected_behavior=new_expected,
                        forbidden_keywords=kw_list,
                    )
                )
                st.success("Yeni test senaryosu eklendi!")
                st.rerun()

with tab_run:
    col_action, col_info = st.columns([1, 3])
    with col_action:
        start_btn = st.button("▶️ Güvenlik Denetimini Başlat", type="primary", use_container_width=True)
    with col_info:
        st.caption(
            f"Seçili Hedef: **{target_mode}** | Hakem: **{judge_model_name}** | "
            f"Toplam Senaryo: **{len(st.session_state.test_cases)}**"
        )

    if start_btn:
        if target_mode == "custom_http" and not target_cfg.endpoint_url.strip():
            st.error("Lütfen sol menüden Hedef Chat API URL adresini girin.")
        else:
            progress_bar = st.progress(0, text="Asenkron test motoru başlatılıyor...")
            judge_cfg = JudgeConfig(
                provider=judge_provider,
                model_name=judge_model_name,
                api_key=judge_api_key,
            )

            def update_progress(done: int, total: int, _res: EvaluationResult) -> None:
                progress_bar.progress(done / total, text=f"Testler çalıştırılıyor ({done}/{total})...")

            t0 = time.perf_counter()
            results = asyncio.run(
                run_test_suite(
                    test_cases=(
                        st.session_state.test_cases
                        if send_pressure_suffix
                        else without_pressure_suffix(st.session_state.test_cases)
                    ),
                    target_config=target_cfg,
                    judge_config=judge_cfg,
                    concurrency=concurrency,
                    rate_limit_delay=rate_limit_delay,
                    on_progress=update_progress,
                )
            )
            st.session_state.last_elapsed = time.perf_counter() - t0
            st.session_state.eval_results = results
            progress_bar.empty()
            st.success(f"Denetim {st.session_state.last_elapsed:.2f} saniyede tamamlandı!")

    if st.session_state.eval_results:
        results: List[EvaluationResult] = st.session_state.eval_results
        summary = summarize(results)
        total_cnt = summary.total
        fail_cnt = summary.violated

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Toplam Test", total_cnt)
        m2.metric("Güvenli (Uyumlu)", summary.passed)
        m3.metric("Tespit Edilen İhlal", fail_cnt, delta=-fail_cnt if fail_cnt > 0 else 0, delta_color="inverse")
        m4.metric("Uyumluluk Skoru", f"%{summary.compliance_rate}")

        if summary.errors:
            st.info(
                f"ℹ️ {summary.errors}/{total_cnt} test hata veya boş yanıt nedeniyle değerlendirilemedi; "
                "bu testler skora dahil edilmedi."
            )

        fallback_cnt = summary.judge_fallbacks
        if fallback_cnt:
            st.warning(
                f"⚠️ {fallback_cnt}/{total_cnt} değerlendirme, hakem API'sine ulaşılamadığı için "
                "**yerel yedek denetçi** ile yapıldı. Bu sonuçlar yalnızca kural tabanlıdır — "
                "API anahtarınızı ve bağlantınızı kontrol edip denetimi yeniden çalıştırmanız önerilir."
            )

        st.subheader("Detaylı Denetim Sonuçları")
        rows = []
        for r in results:
            rows.append(
                {
                    "Durum": _STATUS_LABELS[r.verdict.outcome],
                    "ID": r.test_case.id,
                    "Kategori": r.test_case.category,
                    "Başlık": r.test_case.title,
                    "Hedef Yanıtı": r.target_response,
                    "Hakem Kararı": r.verdict.reason,
                    "Yöntem": r.verdict.evaluation_method,
                    "Süre (ms)": r.latency_ms,
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

with tab_report:
    if not st.session_state.eval_results:
        st.info("Rapor oluşturmak için önce 'Denetimi Çalıştır' sekmesinden testi başlatın.")
    else:
        md_report = generate_markdown_report(
            results=st.session_state.eval_results,
            target_mode=target_mode,
            judge_model=judge_model_name,
            elapsed_seconds=st.session_state.last_elapsed,
        )
        col_dl1, col_dl2 = st.columns(2)
        col_dl1.download_button(
            label="📥 Kurumsal Raporu İndir (.md)",
            data=md_report.encode("utf-8"),
            file_name="owasp_llm_denetim_raporu.md",
            mime="text/markdown",
            use_container_width=True,
        )
        json_dump = json.dumps(
            [r.model_dump() for r in st.session_state.eval_results],
            ensure_ascii=False,
            indent=2,
        )
        col_dl2.download_button(
            label="📥 Ham Sonuçları İndir (.json)",
            data=json_dump.encode("utf-8"),
            file_name="owasp_llm_sonuclar.json",
            mime="application/json",
            use_container_width=True,
        )
        st.divider()
        st.markdown(md_report)
