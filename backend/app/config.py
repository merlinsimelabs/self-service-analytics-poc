import os
from sqlalchemy import create_engine
from dotenv import load_dotenv
import openai


load_dotenv()

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
               )
engine = create_engine(DATABASE_URL)


openai.api_key = os.getenv("OPENAI_API_KEY")
