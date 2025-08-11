import json
from sqlalchemy import text
from openai import OpenAI
import os
import pandas as pd

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def save_schema_metadata(engine, dataset_id, schema_name, metadata):
    """Store schema metadata for later use in LLM prompts."""
    # Convert metadata dict to a JSON string
    metadata_json = json.dumps(metadata)

    with engine.connect() as conn:
        # Use sqlalchemy.text for parameter binding to prevent SQL injection
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
    prompt_context = "I have a dataset with the following tables"
    " and columns:\n\n"

    for table_name, df in tables_dfs.items():
        prompt_context += f"Table: {table_name}\n"
        prompt_context += "Columns:\n"
        for col in df.columns:
            dtype = str(df[col].dtype)
            # Take a small, non-null sample for context
            sample_data = df[col].dropna().head(3).tolist()
            prompt_context += f"- {col} (type: {dtype},sample_data: {sample_data})\n"
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
        sql_query = llm_response.choices[0].message.content.strip().replace("`", "").replace("sql", "")
        return sql_query
    except Exception as e:
        # Raise a specific error that the API endpoint can catch
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
