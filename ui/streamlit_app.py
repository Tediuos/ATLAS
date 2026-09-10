"""Streamlit UI for the ATLAS SEO + WordPress agent."""

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Allow imports from the project root regardless of where Streamlit is launched
sys.path.insert(0, str(Path(__file__).parent.parent))


# ------------------------------------------------------------------ #
#  Page config                                                         #
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="ATLAS",
    page_icon="🔭",
    layout="wide",
)

st.title("🔭 ATLAS — SEO, Content and Social Publishing")
st.caption("Audit · Research · Write · Judge · Review · Publish")

# ------------------------------------------------------------------ #
#  Sidebar — credentials                                               #
# ------------------------------------------------------------------ #

with st.sidebar:
    st.header("⚙️ Configuration")

    st.subheader("WordPress")
    wp_url = st.text_input(
        "Site URL",
        value=os.getenv("WP_URL", ""),
        placeholder="https://yoursite.com",
        help="Your WordPress site root URL.",
    )
    wp_user = st.text_input(
        "Username",
        value=os.getenv("WP_USER", ""),
        placeholder="admin",
    )
    wp_password = st.text_input(
        "Application Password",
        value=os.getenv("WP_APP_PASSWORD", ""),
        type="password",
        help="WordPress Application Password (Settings → Users → Application Passwords).",
    )

    st.divider()
    st.subheader("LLM")
    llm_provider = st.selectbox(
        "Provider",
        ["groq", "ollama"],
        index=0 if os.getenv("LLM_PROVIDER", "groq") == "groq" else 1,
    )
    if llm_provider == "groq":
        groq_key = st.text_input(
            "Groq API Key",
            value=os.getenv("GROQ_API_KEY", ""),
            type="password",
        )
        groq_model = st.text_input(
            "Groq Model",
            value=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        )
    else:
        ollama_model = st.text_input(
            "Ollama Model",
            value=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
        )

    publish_status = st.selectbox(
        "Publish status",
        ["draft", "publish"],
        help="Whether the article is published immediately or saved as a draft.",
    )

# ------------------------------------------------------------------ #
#  Mission input                                                       #
# ------------------------------------------------------------------ #

with st.expander("Reopen a saved mission"):
    saved_id = st.number_input("Mission ID", min_value=1, step=1)
    if st.button("Load saved mission"):
        from atlas.agent import inspect_mission

        try:
            st.session_state.result = inspect_mission(int(saved_id))
        except ValueError as exc:
            st.error(str(exc))

st.subheader("Mission")
mission_text = st.text_area(
    "Describe your SEO mission",
    placeholder=(
        "Audit https://example.com, research keywords for 'best WordPress plugins', "
        "write an article, and publish it as a draft."
    ),
    height=120,
)

run_button = st.button("🚀 Run ATLAS", type="primary", disabled=not mission_text.strip())

# ------------------------------------------------------------------ #
#  Session state                                                       #
# ------------------------------------------------------------------ #

if "result" not in st.session_state:
    st.session_state.result = None
if "logs" not in st.session_state:
    st.session_state.logs = []

# ------------------------------------------------------------------ #
#  Run the agent                                                       #
# ------------------------------------------------------------------ #

if run_button and mission_text.strip():
    # Inject credentials into environment so tools can read them
    os.environ["WP_URL"] = wp_url
    os.environ["WP_USER"] = wp_user
    os.environ["WP_APP_PASSWORD"] = wp_password
    os.environ["LLM_PROVIDER"] = llm_provider
    if llm_provider == "groq":
        os.environ["GROQ_API_KEY"] = groq_key
        os.environ["GROQ_MODEL"] = groq_model
    else:
        os.environ["OLLAMA_MODEL"] = ollama_model

    st.session_state.logs = []
    st.session_state.result = None

    progress_placeholder = st.empty()
    log_placeholder = st.empty()

    def _on_progress(step: str, msg: str) -> None:
        """Append a progress message and refresh the log display."""
        st.session_state.logs.append(f"**[{step}]** {msg}")
        log_placeholder.markdown("\n\n".join(st.session_state.logs[-20:]))

    with st.spinner("ATLAS is working…"):
        try:
            from atlas.agent import run_mission

            result = run_mission(
                mission_text + f"\nRequested WordPress status if publishing: {publish_status}.",
                progress_callback=_on_progress,
            )
            st.session_state.result = result
        except Exception as exc:
            st.error(f"Agent error: {exc}")

    if st.session_state.result:
        progress_placeholder.info(f"Mission status: {st.session_state.result['status']}")

# ------------------------------------------------------------------ #
#  Results                                                             #
# ------------------------------------------------------------------ #

if st.session_state.result:
    result = st.session_state.result

    st.divider()
    st.subheader(f"Mission #{result.get('mission_id')} — Results")

    st.caption(
        f"Status: {result.get('status')} | Planning steps: {result.get('iterations', 0)} | "
        f"Tool calls: {result.get('tool_calls', 0)}"
    )
    if result.get("approvals"):
        approval = result["approvals"][0]
        payload = approval["payload"]
        platform = payload.get("platform", "wordpress")
        platform_label = "LinkedIn" if platform == "linkedin" else "WordPress"
        st.warning(f"{platform_label} post awaiting review")
        st.write(f"Destination: {payload['destination']}")
        if platform == "linkedin":
            st.write(
                f"Author: {payload['post']['author']} | Visibility: {payload['post']['visibility']}"
            )
            st.text(payload["post"]["commentary"])
            with st.expander("Exact LinkedIn API payload"):
                st.json(payload)
        else:
            st.write(f"Status: {payload['post']['status']}")
            st.write(payload["post"]["title"])
            st.code(payload["post"]["content"], language="html")
            st.write(payload["post"]["meta_description"])
        if approval.get("article_judgment"):
            assessment = approval["article_judgment"]
            st.write(f"Article judge: {assessment['overall_score']}/100 ({assessment['mode']})")
            if assessment["scores"]["requires_fact_check"]:
                st.warning("The judge flagged factual verification for human review.")
        approve_col, reject_col = st.columns(2)
        approve = approve_col.button(f"Approve this {platform_label} post", type="primary")
        reject = reject_col.button("Reject this write")
        if approve or reject:
            from atlas.agent import resume_mission

            with st.spinner("Resuming mission..."):
                try:
                    st.session_state.result = resume_mission(
                        result["mission_id"], approve, approval["payload_hash"]
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Resume failed: {type(exc).__name__}")
    with st.expander("Execution metrics"):
        st.json(result.get("metrics", {}))
        st.json(result.get("events", []))

    tab_summary, tab_audit, tab_keywords, tab_article, tab_social, tab_report = st.tabs(
        ["📋 Summary", "🔍 Audit", "🔑 Keywords", "✍️ Article", "LinkedIn", "📄 Report"]
    )

    with tab_summary:
        summary = result.get("summary", "No summary available.")
        st.markdown(summary)

    # ---- Audit tab ----
    with tab_audit:
        audit = result.get("audit")
        if audit:
            score = audit.get("score", 0)
            col1, col2, col3, col4 = st.columns(4)
            lh_scores = (audit.get("lighthouse") or {}).get("scores") or {}
            col1.metric("Overall Score", f"{score}/100")
            col2.metric("Lighthouse SEO", lh_scores.get("seo", "N/A"))
            col3.metric("Performance", lh_scores.get("performance", "N/A"))
            col4.metric("Accessibility", lh_scores.get("accessibility", "N/A"))

            st.subheader("Top SEO Issues")
            issues = audit.get("top_issues") or []
            if issues:
                import pandas as pd

                df = pd.DataFrame(issues)
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No issues data available.")
        else:
            st.info("No audit data in this mission.")

    # ---- Keywords tab ----
    with tab_keywords:
        keyword_data = result.get("keywords")
        if keyword_data and keyword_data.get("keywords"):
            st.dataframe(keyword_data["keywords"], use_container_width=True)
            st.caption("volume_rank is a model heuristic, not measured search volume.")
        else:
            st.info("No keyword research is available for this mission.")

    # ---- Article tab ----
    with tab_article:
        article = result.get("article")
        if article:
            st.markdown(f"**Title:** {article.get('title')}")
            st.markdown(
                f"**Keyword:** `{article.get('target_keyword')}`  |  **Words:** {article.get('word_count')}"
            )
            st.markdown(f"**Meta description:** {article.get('meta_description')}")

            if result.get("judgment"):
                assessment = result["judgment"]
                st.metric("LLM judge score", f"{assessment['overall_score']}/100")
                st.caption(
                    f"{assessment['provider']} / {assessment['model']} | {assessment['rubric_version']} | {assessment['mode']}"
                )
                st.json(assessment["scores"])
            else:
                st.info("No valid judge assessment is available; publication is blocked.")

            with st.expander("Preview HTML content", expanded=True):
                st.html(article.get("html_content", ""))

            if article.get("faq_json_ld"):
                with st.expander("FAQ JSON-LD"):
                    st.code(article["faq_json_ld"], language="html")
        else:
            st.info("No article was written in this mission.")

    with tab_social:
        if result.get("linkedin_post"):
            st.text(result["linkedin_post"]["text"])
        else:
            st.info("No LinkedIn draft is available for this mission.")
        if result.get("linkedin_publish"):
            st.json(result["linkedin_publish"])

    # ---- Report tab ----
    with tab_report:
        st.markdown("Generate a downloadable HTML or PDF report.")

        audit_data = result.get("audit")
        article_data = result.get("article")

        if st.button("Generate HTML Report"):
            from atlas.seo_report import generate_report

            html_report = generate_report(
                audit=audit_data,
                article=article_data,
                keywords=(result.get("keywords") or {}).get("keywords", []),
                publish=result.get("publish"),
            )
            st.download_button(
                label="⬇️ Download HTML Report",
                data=html_report.encode("utf-8"),
                file_name="atlas_seo_report.html",
                mime="text/html",
            )

        st.divider()
        st.markdown("_PDF export requires WeasyPrint (`pip install weasyprint`) and system fonts._")
        if st.button("Generate PDF Report"):
            try:
                from atlas.seo_report import generate_pdf_report

                pdf_bytes = generate_pdf_report(audit=audit_data, article=article_data)
                st.download_button(
                    label="⬇️ Download PDF Report",
                    data=pdf_bytes,
                    file_name="atlas_seo_report.pdf",
                    mime="application/pdf",
                )
            except RuntimeError as exc:
                st.error(str(exc))

# ------------------------------------------------------------------ #
#  Progress log (always visible after a run)                           #
# ------------------------------------------------------------------ #

if st.session_state.logs and not run_button:
    with st.expander("Agent log", expanded=False):
        st.markdown("\n\n".join(st.session_state.logs))
