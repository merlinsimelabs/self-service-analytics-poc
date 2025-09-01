import json
from sqlalchemy import text
from openai import OpenAI
import os
import pandas as pd

from fastapi.responses import JSONResponse

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class UniformResponse(JSONResponse):
    def __init__(self, data=None, error=None, status=200, message="",
                 data_status="success"):
        content = {
            "status": status,
            "data_status": data_status,
            "message": message,
            "data": data if data is not None else {},
            "error": error if error is not None else {}
        }
        super().__init__(status_code=status, content=content)


def save_schema_metadata(
        conn, dataset_id, user_id, user_defined_name, schema_name, metadata):
    """Store the complete dataset metadata in the catalog using a
    provided transaction."""
    metadata_json = json.dumps(metadata)

    stmt = text("""
        INSERT INTO dataset_metadata(
                dataset_id,
                user_id,
                user_defined_name,
                schema_name,
                table_metadata
                )VALUES (
                :dataset_id,
                :user_id,
                :user_defined_name,
                :schema_name,
                :table_metadata)
    """)
    conn.execute(stmt, {
        "dataset_id": dataset_id,
        "user_id": user_id,
        "user_defined_name": user_defined_name,
        "schema_name": schema_name,
        "table_metadata": metadata_json
    })


def get_schema_from_llm(tables_dfs: dict, user_catalog: str):
    """
    Uses an LLM to infer primary keys, foreign keys, and column descriptions
    based on table structure, data samples, and a user-provided catalog.
    """
    prompt_context = "I have a dataset with the following tables"
    " and columns:\n\n"

    for table_name, df in tables_dfs.items():
        prompt_context += f"Table: {table_name}\n"
        prompt_context += "Columns:\n"
        for col in df.columns:
            dtype = str(df[col].dtype)

            sample_data = df[col].dropna().head(3).tolist()
            prompt_context += (
               f"- {col} (type: {dtype}, sample_data: {sample_data})\n"
                )

        prompt_context += "\n"

    system_prompt = f"""
    You are an expert database schema designer. Based on the tables, columns,
    sample data, and user description provided,your task is to identify the
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
            {{"name": "col1", "dtype": "str", "description": "A brief
            description of this column."}},
            {{"name": "col2", "dtype": "int64",
            "description": "Another column description."}}
          ]
        }},
        "table_name_2": {{
          "primary_key": "column_name_or_null",
          "columns": [
            {{"name": "col_a", "dtype": "str",
            "description": "Description for col_a."}}
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

    Rules for your response:
    - The primary key can be null if no obvious single-column primary key
      is found.
    - Provide a concise, one-sentence description for each column based on
      its name and the user's catalog.
    - Ensure the output is a single, clean JSON object with no explanations
      or apologies.
    """

    llm_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
        ],
        temperature=0.1,
        response_format={"type": "json_object"}
    )

    try:
        response_content = llm_response.choices[0].message.content
        schema = json.loads(response_content)
        return schema
    except (json.JSONDecodeError, IndexError) as e:
        print(f"Error decoding LLM response: {e}")
        print(f"Raw response: {llm_response.choices[0].message.content}")
        raise ValueError("Failed to generate a valid schema from the LLM.")


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
      For example: `SELECT * FROM {schema_name}.orders;`.
    - If you need to perform date or time operations (like DATE_TRUNC, EXTRACT,
      or using INTERVAL) on a column that is of type 'object' or 'text' in the
      schema, you MUST explicitly cast it to a date or timestamp. For example,
      use `o.order_date::date` or `CAST(o.order_date AS DATE)`.
    - When a query requires both aggregation (like `SUM`, `AVG` with a
      `GROUP BY`) and a window function (`OVER (...)`), you MUST use a
      Common Table Expression (CTE). First, create a CTE that performs the
      aggregation. Then, select from the CTE and apply the window function to
      the aggregated column. For example: `WITH daily_sales AS (SELECT date,
      SUM(amount) as total_sales FROM sales GROUP BY date) SELECT date,
      AVG(total_sales) OVER (...) FROM daily_sales;`
    - When combining results from multiple SELECT statements:
      * Use **UNION** if you need to eliminate duplicates across result sets.
      * Use **UNION ALL** if you need to keep duplicates (better performance).
      * Choose based on the semantics of the question.
    - Your response must be ONLY the raw SQL query, with no additional text,
      explanations, or markdown.
    """

    try:
        llm_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0
        )
        sql_query = (
                      llm_response.choices[0]
                      .message.content.strip()
                      .replace("`", "")
                      .replace("sql", "")
                  )
        return sql_query
    except Exception as e:
        raise ValueError(f"Failed to generate SQL from LLM. Error: {e}")


def get_chart_suggestion_from_llm(question: str, df: pd.DataFrame) -> dict:
    """Generates a chart suggestion based on the query result."""

    system_prompt = """
    You are a data visualization expert. Given a user's question and the
    columns of the resulting dataset, suggest the most appropriate chart type.
    Your response must be a single JSON object with two keys: "chart_type" and
    "reasoning".Available chart types are: 'bar', 'line', 'pie', 'scatter',
    'table'.Choose 'table' if the data is not suitable for a chart or is best
    displayed as a list.
    """

    user_prompt = f"""
    User's original question: "{question}"
    Resulting data columns: {list(df.columns)}
    Data preview (first 5 rows):
    {df.head().to_string()}
    """

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
        return json.loads(llm_response.choices[0].message.content)
    except Exception as e:
        raise ValueError("Failed to generate chart suggestion from LLM."
                         f" Error: {e}")
