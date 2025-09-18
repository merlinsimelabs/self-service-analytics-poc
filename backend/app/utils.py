import json
import os
import pandas as pd
from sqlalchemy import text
from openai import OpenAI
import logging 

from fastapi.responses import JSONResponse

#initializing logger
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class UniformResponse(JSONResponse):
    """
    Custom JSON response class for consistent API response structure.
    """
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
    """
    Store the complete dataset metadata in the catalog using a provided transaction.
    """
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
    logger.info(f"Metadata saved for dataset_id: {dataset_id}")


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
            sample_data_cleaned = [
                str(x) if isinstance(x, (pd.Timestamp, pd.Timedelta)) else x
                for x in sample_data
            ]
            prompt_context += f"- {col} (type: {dtype}, sample_data: {sample_data_cleaned})\n"
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
    logger.debug(f"Schema LLM system prompt:\n{system_prompt}")
    logger.info("Calling LLM for schema inference...")
    try:
        llm_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        response_content = llm_response.choices[0].message.content
        logger.debug(f"Raw LLM schema response:\n{response_content}")
        return json.loads(response_content)

    except Exception as e:
        logger.error(f"Schema LLM failed: {e}", exc_info=True)
        raise ValueError(f"Failed to generate a valid schema from LLM. Error: {e}")


def get_sql_from_llm(metadata: dict, schema_name: str, question: str) -> str:
    """Generates a SQL query using the LLM based on schema and question."""
    system_prompt = f"""
    You are an expert PostgreSQL query generator. 
    Your task is to produce a **single, correct SQL query** that answers the user's question. 

    Inputs you must consider:
    1. Database schema (in JSON form, provided below).
    2. User's natural language question.
    

    Database Schema:
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
    logger.debug(f"SQL LLM system prompt:\n{system_prompt}\nUser question: {question}")
    logger.info("Calling LLM to generate SQL query...")
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
        logger.info(f"SQL generated: {sql_query}")
        return sql_query

    except Exception as e:
        logger.error(f"SQL LLM failed: {e}", exc_info=True)
        raise ValueError(f"Failed to generate SQL from LLM. Error: {e}")

def get_chart_suggestion_from_llm(question: str, df: pd.DataFrame) -> dict:
    """Generates chart suggestions suitable for ApexCharts, ranked by aptness."""
  
    system_prompt = """
You are an expert in data visualization using ApexCharts. 
Your task is to ALWAYS output a single, strictly valid JSON object that suggests ALL suitable chart types for the given dataset and query.

### 1. Output Format
- JSON must contain:
  - "title": repeat exactly the user query
  - "charts": list of chart objects

Each chart object must include:
- "chart_type": one of ['line','area','bar','histogram','pie','donut','radialBar','scatter','bubble','heatmap','treemap','candlestick','boxPlot','radar','polarArea','rangeBar','table']
- "config": chart configuration following ApexCharts format

### 2. Chart Generation Rules
- Generate ALL logically suitable chart types for the dataset and query.
- Prefer ApexCharts supporting visual charts; 
- Always suggest at least 2 visually meaningful chart types based on the actual dataset.
- Only suggest "table" if no other chart type can meaningfully represent the data.
- Do not omit any chart type that can reasonably represent the data.


### 3. Chart Config Rules

- Trend/Time-Series: 'line','area' → 
  {
    "x":"date_col",
    "series":[{"name":"Metric","y":"value_col"}],
    "markers":{"size":5}
  }
  * Markers must be included to show each point with hover labels and exact values.

- Comparison/Ranking: 'bar','radar' → 
  {
    "x":"category_col",
    "series":[{"name":"Metric","y":"value_col"}]
  }

- Composition/Proportion: 'pie','donut','polarArea','radialBar' → 
  {
    "labels":["cat1","cat2",...],
    "values":[val1,val2,...]
  }
  RULES:
    * Only suggest these chart types if the query requests top N categories AND N ≤ 5.
    * Always use **all top N rows returned by the query** for labels and values; do **not** truncate or limit.
    * Aggregate any remaining rows beyond top N into a single "Other" slice.
    * "Other" value = SUM of all remaining rows; must **never** be 0 unless there are truly no remaining rows.
    * If there are no remaining rows, omit "Other".
    * Total slices = top N + 1 ("Other") if applicable; must **never exceed 6 slices**.
    * NEVER skip, truncate, or use arbitrary defaults for labels or values.

- Distribution: 'histogram','boxPlot' → 
  {
    "x":"num_col",
    "series":[{"name":"Count","y":"count_col"}]
  }

- Relationship: 'scatter','bubble' → 
  {
    "x":"metric1",
    "y":"metric2",
    "size":"metric3_optional"
  }

- Hierarchical/Matrix: 'heatmap','treemap' → 
  {
    "x":"cat1",
    "y":"cat2",
    "values":[...]
  }

- Range/Stock: 'rangeBar','candlestick' → 
  {
    "x":"date_or_cat",
    "series":[{"name":"Metric","y":["low","high"]}]
  }

- Table (last resort): 'table' → 
  {
    "columns":["col1","col2",...]
  }

### 4. Strict Rules
- Always return strictly valid JSON only; no explanations, no extra text.
- Pie/Donut/PolarArea/RadialBar must include **all top N labels and values from the result set**, plus a correctly calculated "Other" slice if there are remaining rows.
- Only suggest Pie/Donut if top N ≤ 5 and total slices ≤ 6 after including "Other".
- Always include **all suitable ApexCharts chart types** that can represent the data; do not omit any.
- NEVER set "Other" = 0 unless there are literally no remaining rows.
- Numeric values must be **exact sums from the dataset**, never estimated.
- Line/Area charts must include markers to show individual points with hover labels and exact values.
- Do not truncate, skip, or limit the number of points, labels, or series under any circumstance.
"""

    user_prompt = f"""
User's original question: "{question}"

Available columns in the dataset: {list(df.columns)}

Data preview (first 5 rows, as JSON):
{json.dumps(data_preview_list, indent=2)}
"""

    logger.debug(f"User prompt for chart LLM:\n{user_prompt}")

    logger.info("Calling LLM for chart suggestion...")
    try:
        llm_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3, 
            response_format={"type": "json_object"}
        )

        content = llm_response.choices[0].message.content
        logger.debug(f"Raw LLM chart suggestion response (length {len(content) if content else 0}):\n{content[:2000]}...")

        return json.loads(content)

    except json.JSONDecodeError as e:
        full_content_log = content if 'content' in locals() else "Content not captured."
        logger.error(f"Chart LLM response was not valid JSON: {e}. Raw content (full):\n{full_content_log}", exc_info=True)
        return {
            "title": question,
            "charts": [
                {"chart_type": "table", "config": {"columns": list(df.columns)}}
            ]
        }
    except Exception as e:
        logger.error(f"Chart LLM failed unexpectedly (check API key/network): {e}", exc_info=True)
        return {
            "title": question,
            "charts": [
                {"chart_type": "table", "config": {"columns": list(df.columns)}}
            ]
        }