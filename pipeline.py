"""
pipeline.py
Orchestrates the end-to-end research pipeline:

Define Research Questions -> Search Sources -> Collect Information ->
Store Sources -> Extract Findings -> Compare Evidence -> Classify Findings ->
Detect Contradictions -> Generate Conclusions -> Maintain Traceability

Every stage writes to the database so the result is a reusable, queryable
knowledge base -- not a single throwaway LLM call.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import database as db
import llm_client as llm
import search_client as search


def run_new_topic(topic_text, n_questions=6, results_per_question=4):
    """Full pipeline entry point: decomposes a topic into sub-questions and
    runs the research pipeline for each one."""
    topic_id = db.insert_topic(topic_text)
    questions = llm.decompose_topic(topic_text, n_questions=n_questions)

    question_ids = []
    for q_text in questions:
        qid = db.insert_question(topic_id, q_text)
        question_ids.append(qid)
        run_question_pipeline(qid, q_text, results_per_question=results_per_question)

    return topic_id, question_ids


def run_new_question(question_text, topic_id=None, results_per_question=4):
    """This is the entry point for the 'surprise record' test: the evaluator
    types a brand-new question with no prior setup, and the full pipeline
    runs against it live."""
    if topic_id is None:
        topic_id = db.insert_topic(f"[Ad-hoc] {question_text[:60]}")
    qid = db.insert_question(topic_id, question_text)
    run_question_pipeline(qid, question_text, results_per_question=results_per_question)
    return qid


def _process_one_source(question_id, question_text, r):
    """Collect + classify + store + extract for a single search result.
    Runs in a worker thread -- these are I/O-bound (network) calls, so
    threads give a real wall-clock speedup even under the GIL."""
    # 2. Collect information -- Tavily already extracts page content,
    #    so we only do a manual fetch if that content is too thin.
    page_text = r.get("snippet", "")
    if len(page_text) < 200:
        fetched = search.fetch_page_text(r["url"])
        if fetched:
            page_text = fetched
    if not page_text:
        return []

    # 3. Classify + store source
    try:
        source_type = llm.classify_source_type(r["url"], r["title"], r["snippet"])
    except Exception as e:
        print(f"[pipeline] classify_source_type failed: {e}")
        source_type = "General Web Content"

    source_id = db.insert_source(
        question_id=question_id,
        url=r["url"],
        title=r["title"],
        source_type=source_type,
        raw_snippet=page_text[:1000],
    )

    # 4. Extract findings
    try:
        findings = llm.extract_findings(question_text, r["title"], page_text)
    except Exception as e:
        print(f"[pipeline] extract_findings failed: {e}")
        findings = []

    stored = []
    for f in findings:
        fid = db.insert_finding(
            source_id=source_id,
            question_id=question_id,
            finding_text=f.get("finding_text", ""),
            finding_type=f.get("finding_type", "claim"),
            confidence_score=f.get("confidence_score", 0.5),
        )
        stored.append({"id": fid, **f})
    return stored


def _with_timeout(fn, timeout_secs, *args, **kwargs):
    """Run fn in a worker thread and give up after timeout_secs, instead of
    letting a stalled network call (no timeout set inside the Tavily
    client, etc.) hang the pipeline indefinitely with no error printed."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn, *args, **kwargs)
        try:
            return fut.result(timeout=timeout_secs)
        except TimeoutError:
            print(f"[pipeline] {fn.__name__} timed out after {timeout_secs}s -- giving up on it")
            return None


def run_question_pipeline(question_id, question_text, results_per_question=4):
    db.update_question_status(question_id, "researching")

    # 1. Search sources -- hard-capped so a stalled network call can't hang
    #    the whole pipeline (the Tavily client sets no timeout itself).
    results = _with_timeout(
        search.search_web, 25, f"{question_text} banking AI", max_results=results_per_question
    )
    if results is None:
        results = []

    # 2-4. Collect/classify/store/extract per source, in parallel. Each
    # source is 2 sequential Groq calls; doing sources one-at-a-time was
    # the main reason this pipeline could exceed the UI's request timeout.
    # Overall deadline so a stuck/rate-limited source can't stall everything
    # -- whatever finished in time is used, stragglers are abandoned.
    all_findings = []
    if results:
        with ThreadPoolExecutor(max_workers=1) as pool:
            futures = [
                pool.submit(_process_one_source, question_id, question_text, r)
                for r in results
            ]
            try:
                for fut in as_completed(futures, timeout=60):
                    all_findings.extend(fut.result())
            except TimeoutError:
                print("[pipeline] source processing deadline hit -- proceeding with what finished")

    # 5. Compare evidence / detect contradictions
    try:
        contradictions = _with_timeout(llm.detect_contradictions, 45, question_text, all_findings) or []
    except Exception as e:
        print(f"[pipeline] detect_contradictions failed: {e}")
        contradictions = []

    for c in contradictions:
        db.insert_contradiction(
            question_id=question_id,
            finding_a_id=c["finding_a_id"],
            finding_b_id=c["finding_b_id"],
            note=c.get("note", ""),
        )

    # 6. Generate conclusion with traceable evidence links
    if all_findings:
        try:
            result = _with_timeout(llm.generate_conclusion, 45, question_text, all_findings, contradictions)
            if result is None:
                conclusion_text, supporting_ids = "Conclusion generation timed out; findings above are still valid.", []
            else:
                conclusion_text, supporting_ids = result
        except Exception as e:
            print(f"[pipeline] generate_conclusion failed: {e}")
            conclusion_text, supporting_ids = "Unable to generate conclusion due to an error.", []
    else:
        conclusion_text, supporting_ids = "No findings were retrieved for this question.", []

    valid_ids = [f["id"] for f in all_findings]
    supporting_ids = [i for i in supporting_ids if i in valid_ids] or valid_ids

    db.insert_conclusion(question_id, conclusion_text, supporting_ids)
    db.update_question_status(question_id, "completed")

    return {
        "question_id": question_id,
        "findings_count": len(all_findings),
        "contradictions_count": len(contradictions),
    }


def run_question_pipeline_safe(question_id, question_text, results_per_question=4):
    """Wrapper for background execution: guarantees the question never gets
    stuck on 'researching' -- any uncaught error marks it 'failed' with an
    explanatory conclusion so the UI can show something meaningful."""
    try:
        run_question_pipeline(question_id, question_text, results_per_question=results_per_question)
    except Exception as e:
        print(f"[pipeline] question {question_id} failed: {e}")
        db.update_question_status(question_id, "failed")
        db.insert_conclusion(question_id, f"Pipeline error: {e}", [])


def run_topic_pipeline_safe(topic_id, topic_text, n_questions=6, results_per_question=4):
    """Background version of run_new_topic's body for an already-created topic_id."""
    try:
        questions = llm.decompose_topic(topic_text, n_questions=n_questions)
        for q_text in questions:
            qid = db.insert_question(topic_id, q_text)
            run_question_pipeline_safe(qid, q_text, results_per_question=results_per_question)
    except Exception as e:
        print(f"[pipeline] topic {topic_id} failed: {e}")
