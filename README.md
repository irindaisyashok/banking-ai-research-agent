# Enterprise AI Research Agent — Banking

**Modus Enterprise AI Build Challenge — Assignment 9**

An AI application that conducts structured, traceable enterprise research at
scale on how AI is transforming banking. It is not "ChatGPT with web
search" — every question decomposes into a persistent, queryable knowledge
base of sources, findings, contradictions and conclusions, and any new
question submitted live runs through the exact same pipeline.

---

## 1. Architecture

```
 USER INTERFACE (Streamlit)
        |  HTTP
 APPLICATION / API LAYER (FastAPI)
        |
 AI INTELLIGENCE LAYER (llm_client.py -> Groq free-tier LLM)
        |
 DATA & KNOWLEDGE LAYER (database.py -> SQLite)
        |
 EXTERNAL RESEARCH (search_client.py -> DuckDuckGo search + page fetch)
```

Each layer is a separate file/module and only talks to the layer directly
below it, so the layers are genuinely decoupled (not cosmetic):

| File | Layer | Responsibility |
|---|---|---|
| `app_streamlit.py` | UI | Renders the app, calls the API over HTTP only |
| `api.py` | Application/API | FastAPI endpoints, request validation |
| `pipeline.py` | Orchestration | Runs the 10-stage research pipeline |
| `llm_client.py` | AI Intelligence | All LLM reasoning calls (Groq) |
| `search_client.py` | External Research | Web search + page text extraction |
| `database.py` | Data & Knowledge | SQLite schema and all persistence |

### Research pipeline (implemented in `pipeline.py`)

```
Define Research Questions
   -> Search Sources
   -> Collect Information
   -> Store Sources
   -> Extract Findings
   -> Classify Findings (source type: Law/Guidance/Standard/Research/Vendor/General)
   -> Compare Evidence
   -> Detect Contradictions
   -> Generate Conclusions (with citations back to finding IDs)
   -> Maintain Traceability (evidence_links table)
```

### Data model (SQLite, see `database.py`)

```
research_topics
research_questions   (belongs to a topic)
sources               (belongs to a question)
findings              (belongs to a source + question)
contradictions        (links two findings)
conclusions            (belongs to a question)
evidence_links         (many-to-many: conclusion <-> findings)
```

Because conclusions link back to specific findings, and findings link back
to specific sources with URLs, every answer is fully traceable — click
"Supporting evidence" in the UI and you see exactly which findings, from
which sources, produced the conclusion.

---

## 2. Why this satisfies the challenge rules

- **Not a single giant prompt / not a ChatGPT wrapper**: the pipeline is
  broken into discrete, auditable stages, each persisted to its own table.
- **Data persists**: SQLite file (`research.db`) — restarting the app does
  not destroy prior research.
- **Processes records systematically, not hard-coded**: `run_new_question()`
  runs the identical pipeline regardless of what question is submitted —
  this is what the "surprise record" test exercises.
- **Free / open-source only**: Groq's free-tier API, DuckDuckGo search
  (no key required), SQLite, FastAPI, Streamlit — no paid licences.
- **Reusable knowledge base**: the "Browse Knowledge Base" tab lets you
  re-query any past topic/question without re-running the pipeline.

**Free-tier disclosure**: If Groq's free tier becomes unavailable or paid,
`llm_client.py` is the only file that needs to change — swap the endpoint
and payload for a locally-run model via Ollama (e.g. `llama3.1:8b`), which
requires no external account at all. If DuckDuckGo search breaks or rate
limits, `search_client.py` is the only file that needs to change — swap in
Tavily's free-tier API, which returns a similar `{title, url, snippet}`
shape.

---

## 3. Setup — step by step

### Prerequisites
- Python 3.10+
- A free Groq API key: sign up at https://console.groq.com (no payment
  method required) and create an API key.

### Steps

1. **Unzip the project** and open a terminal in the project folder.

2. **Create a virtual environment (recommended):**
   ```bash
   python3 -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure your API key:**
   ```bash
   cp .env.example .env
   ```
   Open `.env` and paste your Groq key:
   ```
   GROQ_API_KEY=gsk_your_actual_key_here
   ```

5. **Seed the knowledge base** (pre-populates one banking topic so there's
   existing data to browse before the live demo):
   ```bash
   python seed_data.py
   ```
   This takes 1-3 minutes — it decomposes the topic into ~6 sub-questions
   and runs the full pipeline (search, extract, classify, conclude) for
   each one. You'll see progress printed to the terminal.

6. **Start the API (Terminal 1):**
   ```bash
   uvicorn api:app --reload --port 8000
   ```
   Leave this running. Visit `http://localhost:8000/docs` to see the
   interactive API documentation (Swagger UI) — useful for testing
   endpoints directly.

7. **Start the UI (Terminal 2, new terminal, same venv activated):**
   ```bash
   streamlit run app_streamlit.py
   ```
   This opens the app in your browser at `http://localhost:8501`.

---

## 4. Navigating the app

### Tab 1 — "New Research"

- **Top box ("Ask a new research question")**: type any banking-AI
  research question and click **Run Research Pipeline**. This is the box
  to use for the live evaluator "surprise record" test — it accepts any
  question, with no pre-configuration, and runs the identical 10-stage
  pipeline you'd use for a rehearsed demo. Status messages show each
  pipeline stage as it runs; when finished you see the conclusion plus an
  expandable "Supporting evidence" section listing every finding, its
  source URL, and the source's classification (e.g. Vendor Information vs
  Regulatory Guidance).

- **Bottom box ("Run Full Topic Research")**: enter a broader topic (e.g.
  "How is AI changing credit risk assessment in banking?") and a number of
  sub-questions (3-10). This decomposes the topic and researches every
  sub-question in one go — this is what `seed_data.py` does automatically
  for the default topic.

### Tab 2 — "Browse Knowledge Base"

- Lists every topic researched so far. Expand a topic to see its
  sub-questions and their status. Click **View details** on any question
  to see its conclusion, supporting evidence, and any detected
  contradictions — all pulled live from SQLite via the API, not
  recomputed.

### Direct API access (for the evaluator / technical review)

Visit `http://localhost:8000/docs` for the full interactive Swagger UI.
Key endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/questions` | Submit a brand-new question (surprise-record test) |
| POST | `/topics` | Submit a topic to decompose + research |
| GET | `/topics` | List all researched topics |
| GET | `/questions/{id}/sources` | Raw sources found for a question |
| GET | `/questions/{id}/findings` | Extracted findings for a question |
| GET | `/questions/{id}/contradictions` | Detected contradictions |
| GET | `/questions/{id}/conclusion` | Conclusion + linked supporting evidence |

Example curl for the surprise-record test:
```bash
curl -X POST http://localhost:8000/questions \
  -H "Content-Type: application/json" \
  -d '{"question_text": "How are banks using AI for trade finance document checking?"}'
```

---

## 5. The "1,000 processes tomorrow" scale question

The pipeline is written so scale is a matter of calling `run_new_question`
or `run_new_topic` more times — there is no per-question hard-coded logic
anywhere. For real production scale, the immediate next steps (not built
here due to the 1-day scope) would be:
- Queue-based async processing (e.g. Celery/RQ) instead of synchronous
  in-request pipeline runs, so hundreds of questions can research in
  parallel.
- Swap SQLite for Postgres for concurrent write access.
- Add a vector store (e.g. Chroma, also free/open-source) over the
  `findings` table so "compare evidence" uses semantic similarity search
  rather than passing all findings to the LLM in one prompt — this keeps
  contradiction detection scalable as findings grow into the thousands.
- Cache/deduplicate sources so re-researching overlapping questions
  doesn't re-fetch the same pages.

---

## 6. What was built vs. pre-existing

Pre-existing (disclosed): FastAPI, Streamlit, SQLite (Python stdlib),
`requests`, `beautifulsoup4`, `duckduckgo_search` — all standard
open-source libraries, used as-is per the challenge rules. Everything else
(schema design, pipeline orchestration, all prompts, the API surface, and
the UI) was built for this challenge.
