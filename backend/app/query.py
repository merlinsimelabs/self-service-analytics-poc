import json
import os
import pandas as pd
from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import text
from .config import engine
from openai import OpenAI
router = APIRouter()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@router.post("/query")
async def run_query(payload: dict = Body(...)):
    dataset_id = payload.get("dataset_id")
    question = payload.get("question")

    if not dataset_id or not question:
        raise HTTPException(
            status_code=400,
            detail="dataset_id and question are required"
        )

    # Fetch schema name and metadata from DB
    with engine.connect() as conn:
        sql_meta = text(
            """
            SELECT schema_name, table_metadata
            FROM dataset_metadata
            WHERE dataset_id = :id
            """
        )
        result = conn.execute(sql_meta, {"id": dataset_id}).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Dataset not found")

    schema_name, metadata = result

    # Prepare LLM prompt for SQL generation
    system_prompt = f"""
    You are an expert SQL query generator.
    Given a database schema and user question, write a SQL query that
    answers it.

    Schema (in JSON):
    {json.dumps(metadata, indent=2)}

    IMPORTANT:
    - Use schema name: {schema_name}
    - Fully qualify table names with schema name (e.g., {schema_name}.orders)
    - Do not use LIMIT unless user asks.
    - Return only SQL, no explanation.
    """

    llm_sql = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ],
        temperature=0
    )

    sql_query = llm_sql.choices[0].message.content.strip()

    # Execute generated SQL
    try:
        with engine.connect() as conn:
            query_result = pd.read_sql(text(sql_query), conn)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"SQL execution error: {str(e)}"
        )

    # Prepare LLM prompt for chart suggestion
    chart_prompt = f"""
    You are a data visualization expert.
    Given the following query result columns, suggest the most
    appropriate chart type.

    Columns: {list(query_result.columns)}
    Example chart types: bar, line, pie, scatter, table.

    Respond with only one word for chart type.
    """

    data_preview = query_result.head(5).to_dict(orient="records")

    llm_chart = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": chart_prompt},
            {"role": "user", "content": f"Data preview: {data_preview}"},
        ],
        temperature=0
    )

    chart_type = llm_chart.choices[0].message.content.strip().lower()

    return {
        "dataset_id": dataset_id,
        "sql": sql_query,
        "chart_type": chart_type,
        "result": query_result.to_dict(orient="records")
    }
