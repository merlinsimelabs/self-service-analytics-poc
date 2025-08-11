import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import openai

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set")

engine = create_engine(DATABASE_URL)

# Create metadata table on startup if it doesn't exist
with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS dataset_metadata (
            dataset_id TEXT PRIMARY KEY,
            schema_name TEXT,
            table_metadata JSONB
        )
    """))
    conn.commit()


openai.api_key = os.getenv("OPENAI_API_KEY")
