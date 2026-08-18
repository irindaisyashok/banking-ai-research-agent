"""
seed_data.py
Pre-populates the knowledge base with an initial banking research topic so
the app has existing data to browse before the live demo/surprise-record
test. Run this once after setup.

Usage:
    python seed_data.py
"""

from dotenv import load_dotenv

load_dotenv()

import database as db
import pipeline

DEFAULT_TOPIC = "How is AI transforming fraud detection and financial crime prevention in banking?"

if __name__ == "__main__":
    db.init_db()
    print(f"Seeding topic: {DEFAULT_TOPIC}")
    topic_id, question_ids = pipeline.run_new_topic(DEFAULT_TOPIC, n_questions=6)
    print(f"Done. topic_id={topic_id}, question_ids={question_ids}")
    print("Now start the API and Streamlit app to browse the results.")
