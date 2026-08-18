"""
database.py
Data & Knowledge Layer for the Enterprise AI Research Agent.

Stores: topics, research questions, sources, findings, contradictions,
conclusions, and the evidence links that connect a conclusion back to the
specific findings that support it (traceability requirement).
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "research.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER,
    question_text TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL,
    FOREIGN KEY (topic_id) REFERENCES research_topics(id)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    url TEXT,
    title TEXT,
    source_type TEXT,
    raw_snippet TEXT,
    retrieved_at TEXT NOT NULL,
    FOREIGN KEY (question_id) REFERENCES research_questions(id)
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    finding_text TEXT NOT NULL,
    finding_type TEXT,
    confidence_score REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id),
    FOREIGN KEY (question_id) REFERENCES research_questions(id)
);

CREATE TABLE IF NOT EXISTS contradictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    finding_a_id INTEGER NOT NULL,
    finding_b_id INTEGER NOT NULL,
    contradiction_note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (question_id) REFERENCES research_questions(id),
    FOREIGN KEY (finding_a_id) REFERENCES findings(id),
    FOREIGN KEY (finding_b_id) REFERENCES findings(id)
);

CREATE TABLE IF NOT EXISTS conclusions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    conclusion_text TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    FOREIGN KEY (question_id) REFERENCES research_questions(id)
);

CREATE TABLE IF NOT EXISTS evidence_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conclusion_id INTEGER NOT NULL,
    finding_id INTEGER NOT NULL,
    FOREIGN KEY (conclusion_id) REFERENCES conclusions(id),
    FOREIGN KEY (finding_id) REFERENCES findings(id)
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def now():
    return datetime.utcnow().isoformat()


# --------------------------------------------------------------------------
# Insert helpers
# --------------------------------------------------------------------------

def insert_topic(topic_text):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO research_topics (topic_text, created_at) VALUES (?, ?)",
            (topic_text, now()),
        )
        return cur.lastrowid


def insert_question(topic_id, question_text, status="pending"):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO research_questions (topic_id, question_text, status, created_at) "
            "VALUES (?, ?, ?, ?)",
            (topic_id, question_text, status, now()),
        )
        return cur.lastrowid


def update_question_status(question_id, status):
    with get_conn() as conn:
        conn.execute("UPDATE research_questions SET status=? WHERE id=?", (status, question_id))


def insert_source(question_id, url, title, source_type, raw_snippet):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sources (question_id, url, title, source_type, raw_snippet, retrieved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (question_id, url, title, source_type, raw_snippet, now()),
        )
        return cur.lastrowid


def insert_finding(source_id, question_id, finding_text, finding_type, confidence_score):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO findings (source_id, question_id, finding_text, finding_type, "
            "confidence_score, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, question_id, finding_text, finding_type, confidence_score, now()),
        )
        return cur.lastrowid


def insert_contradiction(question_id, finding_a_id, finding_b_id, note):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO contradictions (question_id, finding_a_id, finding_b_id, "
            "contradiction_note, created_at) VALUES (?, ?, ?, ?, ?)",
            (question_id, finding_a_id, finding_b_id, note, now()),
        )
        return cur.lastrowid


def insert_conclusion(question_id, conclusion_text, finding_ids):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conclusions (question_id, conclusion_text, generated_at) VALUES (?, ?, ?)",
            (question_id, conclusion_text, now()),
        )
        conclusion_id = cur.lastrowid
        for fid in finding_ids:
            conn.execute(
                "INSERT INTO evidence_links (conclusion_id, finding_id) VALUES (?, ?)",
                (conclusion_id, fid),
            )
        return conclusion_id


# --------------------------------------------------------------------------
# Read helpers
# --------------------------------------------------------------------------

def get_topics():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM research_topics ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def get_questions(topic_id=None):
    with get_conn() as conn:
        if topic_id:
            rows = conn.execute(
                "SELECT * FROM research_questions WHERE topic_id=? ORDER BY id", (topic_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM research_questions ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def get_question(question_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM research_questions WHERE id=?", (question_id,)).fetchone()
        return dict(row) if row else None


def get_sources(question_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM sources WHERE question_id=?", (question_id,)).fetchall()
        return [dict(r) for r in rows]


def get_findings(question_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM findings WHERE question_id=?", (question_id,)).fetchall()
        return [dict(r) for r in rows]


def get_source(source_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        return dict(row) if row else None


def get_contradictions(question_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM contradictions WHERE question_id=?", (question_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_conclusion(question_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM conclusions WHERE question_id=? ORDER BY id DESC LIMIT 1", (question_id,)
        ).fetchone()
        return dict(row) if row else None


def get_evidence_for_conclusion(conclusion_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT f.* FROM evidence_links e JOIN findings f ON e.finding_id = f.id "
            "WHERE e.conclusion_id=?",
            (conclusion_id,),
        ).fetchall()
        return [dict(r) for r in rows]
