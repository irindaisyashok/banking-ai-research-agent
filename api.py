"""
api.py
Application / API Layer. Exposes the research pipeline and knowledge base
over HTTP so the UI layer (Streamlit) is fully decoupled from the AI and
data layers, per the mandatory layered architecture.

Run with: uvicorn api:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

import database as db
import pipeline

app = FastAPI(title="Enterprise AI Research Agent - Banking")

# Allow the deployed Streamlit frontend (on a different domain) to call
# this API. Once you have a fixed frontend URL, replace "*" with it for
# tighter security, e.g. ["https://your-app.streamlit.app"].
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()


class TopicRequest(BaseModel):
    topic_text: str
    n_questions: Optional[int] = 6


class QuestionRequest(BaseModel):
    question_text: str
    topic_id: Optional[int] = None


@app.get("/")
def root():
    return {"status": "ok", "service": "Enterprise AI Research Agent - Banking"}


@app.post("/topics")
def create_topic(req: TopicRequest, background_tasks: BackgroundTasks):
    """Returns immediately; sub-questions are created and researched in the
    background. Poll GET /topics/{topic_id}/questions to watch them appear
    and see each one's status move from 'researching' to 'completed'."""
    topic_id = db.insert_topic(req.topic_text)
    background_tasks.add_task(
        pipeline.run_topic_pipeline_safe, topic_id, req.topic_text, req.n_questions
    )
    return {"topic_id": topic_id, "status": "researching"}


@app.get("/topics")
def list_topics():
    return db.get_topics()


@app.get("/topics/{topic_id}/questions")
def list_questions(topic_id: int):
    return db.get_questions(topic_id=topic_id)


@app.post("/questions")
def ask_new_question(req: QuestionRequest, background_tasks: BackgroundTasks):
    """The 'surprise record' entry point: submit any new question and the
    full pipeline (search -> extract -> classify -> compare -> conclude)
    runs against it, in the background. Returns immediately with the new
    question_id and status='researching' -- poll GET /questions/{id} until
    status is 'completed' or 'failed'."""
    topic_id = req.topic_id
    if topic_id is None:
        topic_id = db.insert_topic(f"[Ad-hoc] {req.question_text[:60]}")
    qid = db.insert_question(topic_id, req.question_text)
    background_tasks.add_task(
        pipeline.run_question_pipeline_safe, qid, req.question_text, 2
    )
    return {"question_id": qid, "status": "researching"}


@app.get("/questions/{question_id}")
def get_question(question_id: int):
    q = db.get_question(question_id)
    if not q:
        raise HTTPException(404, "Question not found")
    return q


@app.get("/questions/{question_id}/sources")
def get_sources(question_id: int):
    return db.get_sources(question_id)


@app.get("/questions/{question_id}/findings")
def get_findings(question_id: int):
    return db.get_findings(question_id)


@app.get("/questions/{question_id}/contradictions")
def get_contradictions(question_id: int):
    return db.get_contradictions(question_id)


@app.get("/questions/{question_id}/conclusion")
def get_conclusion(question_id: int):
    conclusion = db.get_conclusion(question_id)
    if not conclusion:
        raise HTTPException(404, "No conclusion yet for this question")
    evidence = db.get_evidence_for_conclusion(conclusion["id"])
    return {"conclusion": conclusion, "evidence": evidence}


@app.get("/sources/{source_id}")
def get_source(source_id: int):
    s = db.get_source(source_id)
    if not s:
        raise HTTPException(404, "Source not found")
    return s
