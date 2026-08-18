"""
app_streamlit.py
User Interface Layer. Talks ONLY to the FastAPI backend over HTTP -- it has
no direct database or LLM access, to keep the layered architecture real
rather than cosmetic.

Run with: streamlit run app_streamlit.py
(after the API is running at http://localhost:8000)
"""

import os
import time

import streamlit as st
import requests

# API_BASE resolves in this order:
# 1. Streamlit Cloud secrets (Settings -> Secrets -> API_BASE = "...")
# 2. Environment variable (useful for other hosts / local override)
# 3. localhost fallback for local development
try:
    API_BASE = st.secrets["API_BASE"]
except Exception:
    API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
POLL_INTERVAL_SECS = 2
POLL_TIMEOUT_SECS = 300  # give up watching after 5 min; the job keeps running server-side regardless


def poll_question_until_done(qid, status_box):
    """Poll GET /questions/{id} until status is 'completed' or 'failed'.
    The pipeline itself runs as a FastAPI background task, so this request
    can never hit an HTTP read timeout -- each poll is a cheap DB read."""
    elapsed = 0
    while elapsed < POLL_TIMEOUT_SECS:
        q = requests.get(f"{API_BASE}/questions/{qid}", timeout=10).json()
        status = q.get("status")
        if status == "completed":
            status_box.update(label="Pipeline complete", state="complete")
            return True
        if status == "failed":
            status_box.update(label="Pipeline failed", state="error")
            return False
        time.sleep(POLL_INTERVAL_SECS)
        elapsed += POLL_INTERVAL_SECS
    status_box.update(label="Still researching... (check back / refresh)", state="running")
    return False

st.set_page_config(page_title="Enterprise AI Research Agent - Banking", layout="wide")
# Theme (warm paper white + mustard accents) is set in .streamlit/config.toml


def render_question_detail(qid):
    q = requests.get(f"{API_BASE}/questions/{qid}").json()
    st.markdown(f"**Question:** {q['question_text']}  \n**Status:** {q['status']}")

    conc_resp = requests.get(f"{API_BASE}/questions/{qid}/conclusion")
    if conc_resp.status_code == 200:
        payload = conc_resp.json()
        conclusion = payload["conclusion"]
        evidence = payload["evidence"]

        st.markdown("### 🧠 Conclusion")
        st.info(conclusion["conclusion_text"])

        with st.expander(f"📎 Supporting evidence ({len(evidence)} findings)", expanded=False):
            for f in evidence:
                src = requests.get(f"{API_BASE}/sources/{f['source_id']}").json()
                st.markdown(
                    f"- **[{f['finding_type']}, confidence={f['confidence_score']}]** "
                    f"{f['finding_text']}"
                )
                st.caption(f"Source: [{src['title']}]({src['url']}) — classified as *{src['source_type']}*")
    else:
        st.warning("No conclusion generated yet for this question.")

    contradictions = requests.get(f"{API_BASE}/questions/{qid}/contradictions").json()
    if contradictions:
        with st.expander(f"⚠️ Contradictions detected ({len(contradictions)})"):
            for c in contradictions:
                st.write(
                    f"Finding {c['finding_a_id']} vs Finding {c['finding_b_id']}: "
                    f"{c['contradiction_note']}"
                )


st.title("🏦 Enterprise AI Research Agent — Banking")
st.caption("Assignment 9 — structured, traceable enterprise research pipeline")

tab1, tab2 = st.tabs(["🔍 New Research", "📚 Browse Knowledge Base"])

with tab1:
    st.subheader("Ask a new research question")
    st.write(
        "This handles the 'surprise record' test — enter **any** banking AI research "
        "question and watch the pipeline run end to end."
    )
    question_text = st.text_input(
        "Research question", placeholder="e.g. How is AI used in trade finance?"
    )

    if st.button("Run Research Pipeline", type="primary"):
        if not question_text.strip():
            st.warning("Please enter a question.")
        else:
            qid = None
            succeeded = False
            with st.status("Running research pipeline...", expanded=True) as status:
                st.write("🔎 Searching sources...")
                st.write("📄 Fetching pages & extracting findings...")
                st.write("🏷️ Classifying source types...")
                st.write("⚖️ Comparing evidence & detecting contradictions...")
                st.write("🧠 Generating traceable conclusion...")
                try:
                    resp = requests.post(
                        f"{API_BASE}/questions", json={"question_text": question_text}, timeout=15
                    )
                    resp.raise_for_status()
                    qid = resp.json()["question_id"]
                    # The pipeline now runs as a background task on the API
                    # side, so we poll for completion instead of blocking
                    # a single HTTP request on it (that's what was timing out).
                    succeeded = poll_question_until_done(qid, status)
                except Exception as e:
                    status.update(label="Pipeline failed", state="error")
                    st.error(f"Pipeline failed: {e}")

            if qid:
                if succeeded:
                    st.success(f"Question processed (id={qid}).")
                else:
                    st.info(f"Question id={qid} is still researching in the background — refresh or check the Knowledge Base tab shortly.")
                render_question_detail(qid)

    st.divider()
    st.subheader("Or seed a full topic (multiple sub-questions at once)")
    topic_text = st.text_input(
        "Topic", placeholder="e.g. How is AI transforming fraud detection in banking?"
    )
    n_q = st.slider("Number of sub-questions", 3, 10, 6)
    if st.button("Run Full Topic Research"):
        if not topic_text.strip():
            st.warning("Please enter a topic.")
        else:
            try:
                resp = requests.post(
                    f"{API_BASE}/topics",
                    json={"topic_text": topic_text, "n_questions": n_q},
                    timeout=15,
                )
                resp.raise_for_status()
                topic_id = resp.json()["topic_id"]
            except Exception as e:
                st.error(f"Failed: {e}")
                topic_id = None

            if topic_id:
                with st.status(
                    "Decomposing topic and researching each sub-question...", expanded=True
                ) as status:
                    elapsed, seen_ids, done_count = 0, set(), 0
                    while elapsed < POLL_TIMEOUT_SECS:
                        qs = requests.get(f"{API_BASE}/topics/{topic_id}/questions", timeout=10).json()
                        for q in qs:
                            if q["id"] not in seen_ids:
                                seen_ids.add(q["id"])
                                st.write(f"➕ {q['question_text']}")
                        done_count = sum(1 for q in qs if q["status"] in ("completed", "failed"))
                        if qs and done_count == len(qs) and done_count == n_q:
                            status.update(
                                label=f"Topic complete — {done_count} sub-questions researched",
                                state="complete",
                            )
                            break
                        time.sleep(POLL_INTERVAL_SECS)
                        elapsed += POLL_INTERVAL_SECS
                    else:
                        status.update(label="Still researching... check the Knowledge Base tab shortly", state="running")
                st.success(f"Topic created (id={topic_id}).")

with tab2:
    st.subheader("Browse existing topics")
    try:
        topics = requests.get(f"{API_BASE}/topics").json()
    except Exception as e:
        topics = []
        st.error(f"Could not reach API: {e}")

    if not topics:
        st.write("No topics yet. Run a research topic in the first tab.")
    else:
        topic_options = {f"{t['topic_text']} (id={t['id']})": t["id"] for t in topics}
        selected_topic_label = st.selectbox("Select a topic", list(topic_options.keys()))
        selected_topic_id = topic_options[selected_topic_label]

        questions = requests.get(f"{API_BASE}/topics/{selected_topic_id}/questions").json()
        if questions:
            q_options = {
                f"Q{q['id']}: {q['question_text']}  — {q['status']}": q["id"] for q in questions
            }
            selected_q_label = st.selectbox("Select a question", list(q_options.keys()))
            st.divider()
            render_question_detail(q_options[selected_q_label])
        else:
            st.write("No questions under this topic yet.")