import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import openai

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set")

engine = create_engine(DATABASE_URL)


with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS dataset_metadata (
            dataset_id TEXT PRIMARY KEY,
            user_id TEXT,
            user_defined_name TEXT UNIQUE NOT NULL,
            schema_name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            table_metadata JSONB
        );
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS dashboards (
            dashboard_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            dataset_id TEXT REFERENCES dataset_metadata(dataset_id),
            dashboard_name TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS dashboard_charts (
            chart_id TEXT PRIMARY KEY,
            dashboard_id TEXT REFERENCES dashboards(dashboard_id) ON DELETE CASCADE,
            chart_type TEXT NOT NULL,
            sql_query TEXT NOT NULL,
            chart_config JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """))
    conn.commit()


openai.api_key = os.getenv("OPENAI_API_KEY")