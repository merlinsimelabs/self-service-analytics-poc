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
    You are an expert PostgreSQL query generator. 
    Given the database schema and user question, write a single, syntactically correct
    PostgreSQL query that answers the question.

    Database Schema / Catalog (in JSON format):
    {json.dumps(metadata, indent=2)}

    IMPORTANT RULES:
    - ALWAYS qualify table names with the schema name: `{schema_name}`.
      For example: `SELECT * FROM {schema_name}.orders;`.
    - Use the provided schema/catalog as the ONLY source of truth for available tables, columns,
      datatypes, and relationships. Do not assume extra fields or tables.
    - If you need to perform date or time operations (like DATE_TRUNC, EXTRACT,
      or using INTERVAL) on a column that is of type 'object' or 'text' in the
      schema, you MUST explicitly cast it to a date or timestamp. 
      Example: `o.order_date::date` or `CAST(o.order_date AS DATE)`.
    - When a query requires both aggregation (like SUM, AVG with a GROUP BY) 
      and a window function (OVER (...)), you MUST use a Common Table Expression (CTE). 
      First create a CTE that performs the aggregation, then select from the CTE 
      and apply the window function to the aggregated column.
      Example:
        WITH daily_sales AS (
            SELECT date, SUM(amount) as total_sales
            FROM sales
            GROUP BY date
        )
        SELECT date, AVG(total_sales) OVER (...)
        FROM daily_sales;
    - When combining results from multiple SELECT statements:
      * Use UNION if you need to eliminate duplicates across result sets.
      * Use UNION ALL if you need to keep duplicates (better performance).
      * Choose based on the semantics of the user question.
    - When comparing one row’s result to another (e.g. difference from previous customer), 
      use window functions like LAG() or LEAD() with ORDER BY.
    - Always ensure that aggregations happen at the correct entity level 
      (e.g., per customer, per order, per account) as implied by the question.
    - Do not include any explanation, markdown, or commentary in your response. 
      Output ONLY the raw SQL query.
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
    """
    Generates a chart suggestion (type and config) based on the query result
    and the user's original question.
    The chart_config includes suggested column mappings for the chart.
    """

    # Identify column types for better LLM hints
    column_info = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        is_numeric = pd.api.types.is_numeric_dtype(df[col])
        is_datetime = pd.api.types.is_datetime64_any_dtype(df[col])
        # Simple heuristic for categorical: not numeric and few unique values
        is_categorical = not is_numeric and df[col].nunique() < min(len(df), 20)

        column_info.append({
            "name": col,
            "type": dtype,
            "is_numeric": is_numeric,
            "is_datetime": is_datetime,
            "is_categorical": is_categorical,
            "unique_values": df[col].nunique() # Useful for cardinality
        })

    system_prompt = f"""
    You are a data visualization expert. Given a user's question, the columns of the
    resulting dataset, and their types, suggest the most appropriate chart type
    and a default configuration for it.

    Your response must be a single JSON object with two keys:
    "chart_type": The suggested chart type ('bar', 'line', 'pie', 'scatter', 'table', 'area').
    "reasoning": A brief explanation for the chart choice.
    "chart_config": A JSON object containing specific configuration for the chart,
                    especially column mappings.

    Available chart types and their primary configurations:
    - 'bar': For comparing categories. Needs 'x_column' (category) and 'y_column' (measure).
    - 'line': For showing trends over time or ordered categories. Needs 'x_column' (time/order) and 'y_column' (measure).
    - 'area': Similar to line, for showing magnitude of change over time. Needs 'x_column' (time/order) and 'y_column' (measure).
    - 'pie': For showing proportions of a whole. Needs 'label_column' (category) and 'value_column' (measure).
    - 'scatter': For showing relationships between two numerical variables. Needs 'x_column' (measure) and 'y_column' (measure).
    - 'table': If the data is not suitable for a graphical chart or is best displayed as raw numbers. No specific column mappings needed for 'table'.

    Consider these rules for column mapping:
    - For 'x_column'/'y_column' in bar/line/area/scatter: Prioritize numerical columns for measures, and categorical/datetime for categories/time.
    - For 'pie' chart: 'value_column' must be numerical. 'label_column' should be categorical and have a reasonable number of unique values (e.g., less than 15-20)
    - If no obvious columns fit a chart type, or if there are too many columns for a simple chart (e.g., more than 2-3 main columns for visualization), default to 'table'.
    - Ensure the suggested columns actually exist in the provided 'Resulting data columns'.

    User's original question: "{question}"

    Resulting data columns and their properties:
    {json.dumps(column_info, indent=2)}

    Data preview (first 5 rows):
    {df.head().to_string()}

    Please respond with ONLY a single, valid JSON object.
    Example for a bar chart:
    {{
      "chart_type": "bar",
      "reasoning": "Bar chart is suitable for comparing sales across different product categories.",
      "chart_config": {{
        "x_column": "product_category",
        "y_column": "total_sales"
      }}
    }}
    Example for a pie chart:
    {{
      "chart_type": "pie",
      "reasoning": "Pie chart effectively shows the distribution of market share by region.",
      "chart_config": {{
        "label_column": "region",
        "value_column": "market_share_percentage"
      }}
    }}
    Example for a table:
    {{
      "chart_type": "table",
      "reasoning": "The data is tabular and best viewed directly as a list of detailed records.",
      "chart_config": {{}}
    }}
    """

    try:
        llm_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Given the question: '{question}' and data with columns {list(df.columns)}, suggest a chart type and configuration."}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        response_content = llm_response.choices[0].message.content
        chart_suggestion = json.loads(response_content)

        # The 'data' field might be large, consider if you want to store it here
        # or have the frontend re-fetch based on sql_query and dataset_id.
        # For this PoC, storing it directly in chart_config is simpler for the frontend.
        chart_suggestion['chart_config']['data'] = df.to_dict(orient="records")
        chart_suggestion['chart_config']['columns'] = list(df.columns)
        chart_suggestion['chart_config']['original_question'] = question
        
        return chart_suggestion
    except Exception as e:
        print(f"Error generating chart suggestion from LLM: {e}")
        # Fallback to a default table suggestion if LLM fails
        return {
            "chart_type": "table",
            "reasoning": "Failed to generate a chart suggestion. Displaying as table.",
            "chart_config": {
                "data": df.to_dict(orient="records"),
                "columns": list(df.columns),
                "original_question": question
            }
        }