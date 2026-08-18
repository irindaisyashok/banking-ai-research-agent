"""
llm_client.py
AI Intelligence Layer — wraps a free-tier LLM (Groq's OpenAI-compatible API)
for every reasoning step in the pipeline: decomposition, extraction,
classification, contradiction detection, and conclusion generation.

Swap-out note: Groq is used here because it has a generous free tier and is
fast. If Groq ever becomes unavailable or paid, this module can be pointed at
a local model instead (e.g. Ollama running llama3.1:8b) by changing GROQ_URL
and the request/response shape in `_chat`. No other file needs to change.
"""

import os
import json
import time
import requests

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _chat(messages, temperature=0.2, max_tokens=1500, json_mode=False, retries=3):
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Create a free key at https://console.groq.com "
            "and add it to your .env file."
        )
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
            if resp.status_code == 429:
                # Cap the wait so one rate-limited call can't stall the
                # whole pipeline for tens of seconds -- 3 short retries
                # then give up and let the caller's fallback kick in.
                wait = min(float(resp.headers.get("Retry-After", 3 * attempt)), 8)
                print(f"[llm_client] Groq rate-limited (attempt {attempt}/{retries}), waiting {wait:.1f}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            last_error = e
            print(f"[llm_client] request failed (attempt {attempt}/{retries}): {e}")
            time.sleep(min(2 * attempt, 6))

    raise RuntimeError(f"Groq API call failed after {retries} attempts: {last_error}")

def _safe_json(content, fallback):
    try:
        return json.loads(content)
    except Exception:
        return fallback


def decompose_topic(topic_text, n_questions=6):
    prompt = f"""You are a banking industry research planner.
Topic: "{topic_text}"

Break this topic into {n_questions} specific, researchable sub-questions about how AI is
used in banking, related to this topic. Each question should be answerable by researching
public sources (news, regulator guidance, vendor whitepapers, academic papers).

Respond ONLY with valid JSON in this exact format:
{{"questions": ["question 1", "question 2", ...]}}
"""
    content = _chat([{"role": "user", "content": prompt}], json_mode=True)
    data = _safe_json(content, {"questions": []})
    return data.get("questions", [])


def extract_findings(question_text, source_title, source_text):
    source_text = source_text[:1500]  # trimmed from 4000 -- cuts input tokens ~60%
    prompt = f"""You are a research analyst extracting factual findings from a source document.

Research question: "{question_text}"
Source title: "{source_title}"
Source content:
\"\"\"{source_text}\"\"\"

Extract up to 3 distinct, atomic factual findings from this source that are relevant to the
research question. For each finding, classify its type as one of:
"fact", "statistic", "claim", "opinion".
Also give a confidence_score between 0 and 1 for how well-supported/clear the finding is.

Respond ONLY with valid JSON:
{{"findings": [
  {{"finding_text": "...", "finding_type": "fact", "confidence_score": 0.8}}
]}}
If nothing relevant is present, return {{"findings": []}}.
"""
    content = _chat([{"role": "user", "content": prompt}], json_mode=True, max_tokens=500)
    data = _safe_json(content, {"findings": []})
    return data.get("findings", [])


def classify_source_type(url, title, snippet):
    prompt = f"""Classify the following web source into exactly one category:
"Law/Regulation", "Regulatory Guidance", "Industry Standard", "Research",
"Vendor Information", "General Web Content".

URL: {url}
Title: {title}
Snippet: {snippet[:300]}

Respond ONLY with valid JSON: {{"source_type": "..."}}
"""
    content = _chat([{"role": "user", "content": prompt}], json_mode=True, temperature=0, max_tokens=30)
    data = _safe_json(content, {"source_type": "General Web Content"})
    return data.get("source_type", "General Web Content")


def detect_contradictions(question_text, findings):
    if len(findings) < 2:
        return []
    findings_list = "\n".join([f"[{f['id']}] {f['finding_text']}" for f in findings])
    prompt = f"""You are reviewing research findings for contradictions.

Research question: "{question_text}"
Findings:
{findings_list}

Identify pairs of findings (by id) that meaningfully contradict or conflict with each other.
Respond ONLY with valid JSON:
{{"contradictions": [
  {{"finding_a_id": 1, "finding_b_id": 2, "note": "explanation of the conflict"}}
]}}
If there are no contradictions, return {{"contradictions": []}}.
"""
    content = _chat([{"role": "user", "content": prompt}], json_mode=True, max_tokens=400)
    data = _safe_json(content, {"contradictions": []})
    return data.get("contradictions", [])


def generate_conclusion(question_text, findings, contradictions):
    # Cap to the most confident findings so the prompt/response stays a
    # manageable size -- a very long findings list can push the LLM's
    # response past its token limit and get truncated mid-JSON.
    findings = sorted(findings, key=lambda f: f.get("confidence_score", 0), reverse=True)[:12]

    findings_list = "\n".join(
        [f"[{f['id']}] ({f['finding_type']}, conf={f['confidence_score']}) {f['finding_text']}"
         for f in findings]
    )
    contradiction_note = ""
    if contradictions:
        contradiction_note = "\nThe following contradictions were detected:\n" + "\n".join(
            [f"- Finding {c['finding_a_id']} vs {c['finding_b_id']}: {c['note']}" for c in contradictions]
        )
    prompt = f"""You are a senior banking industry research analyst writing a conclusion.

Research question: "{question_text}"

Findings gathered:
{findings_list}
{contradiction_note}

Write a concise, evidence-based conclusion (120-200 words) answering the research question.
Where relevant, reference specific finding ids in square brackets, e.g. [3].
Explicitly mention any contradictions/uncertainty if present.
Keep the conclusion_text field itself under 1500 characters.

Respond ONLY with valid JSON:
{{"conclusion_text": "...", "supporting_finding_ids": [1,2,3]}}
"""
    content = _chat([{"role": "user", "content": prompt}], json_mode=True, max_tokens=700)
    data = _safe_json(content, None)
    if data is None:
        fallback_text = content.strip()
        if len(fallback_text) > 1500:
            fallback_text = fallback_text[:1500] + "..."
        return fallback_text, [f["id"] for f in findings]
    return data.get("conclusion_text", ""), data.get("supporting_finding_ids", [])