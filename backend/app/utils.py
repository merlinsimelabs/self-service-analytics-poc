import json
import os
import pandas as pd
from sqlalchemy import text
from openai import OpenAI


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



def save_schema_metadata(engine, dataset_id, schema_name, metadata):
    """Store schema metadata for later use in LLM prompts."""
    metadata_json = json.dumps(metadata)

    with engine.connect() as conn:
        stmt = text("""
            INSERT INTO dataset_metadata
            (dataset_id, schema_name, table_metadata)
            VALUES (:dataset_id, :schema_name, :table_metadata)
            ON CONFLICT (dataset_id) DO UPDATE SET
            schema_name = EXCLUDED.schema_name,
            table_metadata = EXCLUDED.table_metadata;
        """)
        conn.execute(stmt, {
            "dataset_id": dataset_id,
            "schema_name": schema_name,
            "table_metadata": metadata_json
        })
        conn.commit()



def get_schema_from_llm(tables_dfs: dict, user_catalog: str):
    """
    Uses an LLM to infer primary keys, foreign keys, and column descriptions
    based on table structure, data samples, and a user-provided catalog.
    """
    prompt_context = "I have a dataset with the following tables:\n\n"

    for table_name, df in tables_dfs.items():
        prompt_context += f"Table: {table_name}\nColumns:\n"
        for col in df.columns:
            dtype = str(df[col].dtype)
            sample_data = df[col].dropna().head(3).tolist()
            prompt_context += f"- {col} (type: {dtype}, sample_data: {sample_data})\n"
        prompt_context += "\n"

    system_prompt = f"""
    You are an expert database schema designer. Based on the tables, columns,
    sample data, and user description provided, your task is to identify the
    schema structure. Specifically, identify primary keys and foreign key
    relationships.

    User's description of the dataset (the catalog):
    ---
    {user_catalog}
    ---

    Tables, Columns, and Data Samples:
    ---
    {prompt_context}
    ---

    Please respond with ONLY a single, valid JSON object that follows this
    exact structure:
    {{
      "tables": {{
        "table_name_1": {{
          "primary_key": "column_name_or_null",
          "columns": [
            {{"name": "col1", "dtype": "str", "description": "A brief description."}},
            {{"name": "col2", "dtype": "int64", "description": "Another description."}}
          ]
        }},
        "table_name_2": {{
          "primary_key": "column_name_or_null",
          "columns": [
            {{"name": "col_a", "dtype": "str", "description": "Description for col_a."}}
          ]
        }}
      }},
      "relationships": [
        {{
          "from_table": "table_with_foreign_key",
          "from_column": "foreign_key_column",
          "to_table": "table_with_primary_key",
          "to_column": "primary_key_column"
        }}
      ]
    }}
    """

    print(" Calling LLM for schema...")
    try:
        llm_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.1,
          
            response_format={"type": "json_object"},
        )

        response_content = llm_response.choices[0].message.content
        return json.loads(response_content)

    except Exception as e:
        print(f"Schema LLM failed: {e}")
        raise ValueError("Failed to generate a valid schema from LLM.")



def get_sql_from_llm(metadata: dict, schema_name: str, question: str) -> str:
    """Generates a SQL query using the LLM based on schema and question."""
    system_prompt = f"""
    You are an expert PostgreSQL query generator. Given the database schema
    below and a user question, write a single, syntactically correct
    PostgreSQL query that answers the question.

    Database Schema (in JSON format):
    {json.dumps(metadata, indent=2)}

    IMPORTANT RULES:
    - ALWAYS qualify table names with the schema name: `{schema_name}`.
    - If you need to perform date/time ops on a text column, CAST it explicitly.
    - If aggregation + window function is needed, use a CTE.
    - Respond ONLY with the raw SQL query.
    """

    print("Calling LLM for SQL...")
    try:
        llm_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0,
            
        )
        sql_query = (
            llm_response.choices[0].message.content.strip()
            .replace("`", "").replace("sql", "")
        )
        print(f"SQL generated: {sql_query}")
        return sql_query

    except Exception as e:
        print(f"SQL LLM failed: {e}")
        raise ValueError(f"Failed to generate SQL from LLM. Error: {e}")



def get_chart_suggestion_from_llm(question: str, df: pd.DataFrame) -> dict:
    """Generates chart suggestions suitable for ApexCharts, ranked by aptness."""
    system_prompt = """
You are a data visualization expert specializing in ApexCharts.

STRICT RULES for chart suggestions:
1. Always return a single valid JSON object with:
   - "title": the exact user query from the user
   - "charts": a list of chart objects

2. Each chart object must include:
   - "chart_type": one of ['line','area','bar','histogram','pie','donut',
     'radialBar','scatter','bubble','heatmap','treemap','candlestick','boxPlot',
     'radar','polarArea','rangeBar','table']
   - "config": mapping of dataset columns:
       - bar/line/area: { "x": "column_name", "series": [{"name": "metric1", "y": "column_name"}, {"name": "metric2", "y": "column_name"}, ...] }
       - pie/donut/polarArea: { "labels": ["top N categories", "Other"], "values": ["top N metric values", "remaining value"] }
       - scatter/bubble: { "x": "column_name", "y": ["metric1", "metric2", ...], "size": "column_name" }  # allow multiple y-metrics
       - heatmap/treemap: { "x": "column_name", "y": "column_name", "values": ["metric1", "metric2", ...] }  # allow multiple metrics
       - table: { "columns": ["col1","col2",...] }

3. If the user query mentions "top N" (e.g., top 10 customers):
   - Charts should include only top N.
   - For pie/donut/polarArea, include an additional "Other" slice to represent remaining data.
4. - Suggest both 'pie' and 'donut' as separate charts even if the configuration is similar.
5. - Each chart object must have its own 'chart_type' and 'config'.
6. Suggest **multiple chart types (≥2)** covering all suitable charts, not just bar.

7. If the dataset is unsuitable for charts, return only "table" with relevant columns.

8. The JSON must be strictly valid, parseable, and contain no reasoning, explanations, or extra fields.
"""


    user_prompt = f"""
    User's original question: "{question}"
    Available data columns: {list(df.columns)}
    Data preview (first 5 rows):
    {df.head().to_string()}
    """

    print("Calling LLM for chart suggestion...")
    try:
        llm_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            
            response_format={"type": "json_object"}
        )

        content = llm_response.choices[0].message.content
        return json.loads(content)

    except Exception as e:
        print(f"Chart LLM failed: {e}")
        # fallback = simple table suggestion
        return {
            "title": question,
            "charts": [
                {"chart_type": "table", "config": {"columns": list(df.columns)}}
            ]
        }
