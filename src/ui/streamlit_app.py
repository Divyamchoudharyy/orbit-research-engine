import os
import threading
import time

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")
if not API_BASE.startswith(("http://", "https://")):
    API_BASE = f"https://{API_BASE}"
API_KEY = os.getenv("ORBIT_API_KEY", "")
API_HEADERS = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


def reset_job_state():
    st.session_state.job_id = None
    st.session_state.logs = []
    st.session_state.thread_active = [False]
    st.session_state.stream_thread = None


@st.cache_data(ttl=60)
def check_health(api_base: str):
    try:
        return requests.get(f"{api_base}/health", timeout=5).json()
    except requests.RequestException:
        return None


st.set_page_config(
    page_title="ORBIT — Deep Research Engine",
    page_icon="🔬",
    layout="wide",
)

st.title("🔬 ORBIT — Deep Research Engine")
st.caption("Multi-agent research pipeline: Planner → Researcher → Critic → Writer")

with st.sidebar:
    st.header("Settings")
    depth = st.selectbox(
        "Research depth",
        options=["quick", "standard", "deep"],
        index=1,
        help="quick ~20s | standard ~45s | deep ~90s",
    )
    st.divider()
    st.markdown(f"**API:** `{API_BASE}`")
    health = check_health(API_BASE)
    if health:
        st.success(f"API online — v{health.get('version', '?')}")
    else:
        st.error("API offline — check API_BASE and API deployment")
    if not API_KEY:
        st.error("ORBIT_API_KEY is not configured for the UI service.")

if "job_id" not in st.session_state:
    st.session_state.job_id = None
if "query" not in st.session_state:
    st.session_state.query = ""
if "logs" not in st.session_state:
    st.session_state.logs = []
if "thread_active" not in st.session_state:
    st.session_state.thread_active = [False]
if "stream_thread" not in st.session_state:
    st.session_state.stream_thread = None

if not st.session_state.job_id:
    query = st.text_area(
        "Research query",
        value=st.session_state.query,
        placeholder="e.g. What are the latest breakthroughs in protein folding AI?",
        height=100,
    )

    if st.button("🚀 Start Research", type="primary", disabled=not query.strip()):
        try:
            response = requests.post(
                f"{API_BASE}/research",
                json={"query": query.strip(), "depth": depth},
                headers=API_HEADERS,
                timeout=15,
            )
            response.raise_for_status()
            job = response.json()
            st.session_state.job_id = job["job_id"]
            st.session_state.query = query.strip()
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Failed to submit job: {exc}")

else:
    job_id = st.session_state.job_id
    st.info(f"Active Job ID: `{job_id}`")

    try:
        status_response = requests.get(
            f"{API_BASE}/jobs/{job_id}/status",
            headers=API_HEADERS,
            timeout=10,
        )
        status_response.raise_for_status()
        status_data = status_response.json()
        current_status = status_data.get("status", "unknown")
    except requests.RequestException as exc:
        st.error(f"Error fetching job status: {exc}")
        if st.button("🔄 Reset / Start New"):
            reset_job_state()
            st.rerun()
        st.stop()

    if current_status in ("pending", "running"):
        st.subheader("📡 Real-time Research Logs")

        if not st.session_state.thread_active[0]:
            st.session_state.logs = []
            st.session_state.thread_active = [True]

            def log_collector(job, logs_list, active_flag):
                try:
                    import json

                    with requests.get(
                        f"{API_BASE}/jobs/{job}/stream",
                        headers=API_HEADERS,
                        stream=True,
                        timeout=(10, 45),
                    ) as response:
                        response.raise_for_status()
                        for line in response.iter_lines():
                            if not active_flag[0]:
                                break
                            if line:
                                decoded = line.decode("utf-8").strip()
                                if decoded.startswith("data:"):
                                    payload_text = decoded[5:].strip()
                                    if payload_text:
                                        try:
                                            payload = json.loads(payload_text)
                                            if payload.get("type") == "log":
                                                logs_list.append(payload.get("message"))
                                        except (ValueError, TypeError):
                                            continue
                except requests.RequestException:
                    pass
                finally:
                    active_flag[0] = False

            thread = threading.Thread(
                target=log_collector,
                args=(
                    job_id,
                    st.session_state.logs,
                    st.session_state.thread_active,
                ),
                daemon=True,
            )
            thread.start()
            st.session_state.stream_thread = thread

        if st.session_state.logs:
            st.code("\n".join(st.session_state.logs), language="text")
        else:
            st.info("Waiting for logs from research worker...")

        time.sleep(1)
        st.rerun()

    elif current_status == "awaiting_human":
        st.warning("⚡ Human-in-the-Loop: Review Required")
        hil = status_data.get("hil_payload", {}) or {}
        st.markdown(
            f"**Iteration {hil.get('iteration', '?')}/"
            f"{hil.get('max_iterations', '?')} — Critic found research gaps:**"
        )
        for gap in hil.get("gaps", []):
            st.markdown(f"• {gap}")

        expires_at = hil.get("expires_at")
        if expires_at:
            st.caption(f"⏱ Auto-finalizes at {expires_at} (UTC) if no response")

        col_continue, col_finalize = st.columns(2)
        with col_continue:
            if st.button("🔍 Continue Researching", type="primary"):
                try:
                    response = requests.post(
                        f"{API_BASE}/jobs/{job_id}/decision",
                        json={"decision": "continue"},
                        headers=API_HEADERS,
                        timeout=10,
                    )
                    response.raise_for_status()
                    st.success("Routing back to Researcher...")
                    time.sleep(1)
                    st.rerun()
                except requests.RequestException as exc:
                    st.error(f"Failed to send decision: {exc}")
        with col_finalize:
            if st.button("✍️ Finalize Now"):
                try:
                    response = requests.post(
                        f"{API_BASE}/jobs/{job_id}/decision",
                        json={"decision": "finalize"},
                        headers=API_HEADERS,
                        timeout=10,
                    )
                    response.raise_for_status()
                    st.success("Skipping to Writer...")
                    time.sleep(1)
                    st.rerun()
                except requests.RequestException as exc:
                    st.error(f"Failed to send decision: {exc}")

    elif current_status == "failed":
        st.error("❌ Research job failed.")
        if st.button("🔄 Reset / Start New"):
            reset_job_state()
            st.rerun()

    elif current_status == "complete":
        st.success("✅ Research complete!")
        try:
            result_response = requests.get(
                f"{API_BASE}/jobs/{job_id}/result",
                headers=API_HEADERS,
                timeout=15,
            )
            result_response.raise_for_status()
            result_data = result_response.json()
        except requests.RequestException as exc:
            st.error(f"Failed to fetch result: {exc}")
            st.stop()

        col_status, col_iterations, col_sources = st.columns(3)
        col_status.metric("Status", result_data.get("status", "?").upper())
        col_iterations.metric("Research iterations", result_data.get("agent_turns", "?"))
        col_sources.metric("Sources found", len(result_data.get("sources") or []))

        st.subheader("📄 Research Report")
        report = result_data.get("report", "")
        if report:
            st.markdown(report)
        else:
            st.warning("No report content returned.")

        sources = result_data.get("sources") or []
        if sources:
            with st.expander(f"🔗 Sources ({len(sources)})"):
                for index, url in enumerate(sources, 1):
                    st.markdown(f"{index}. {url}")

        col_download, col_reset = st.columns([3, 1])
        if report:
            with col_download:
                st.download_button(
                    label="⬇️ Download report as Markdown",
                    data=report,
                    file_name=f"research_{job_id[:8]}.md",
                    mime="text/markdown",
                )
        with col_reset:
            if st.button("🔄 Start New Research"):
                reset_job_state()
                st.rerun()
