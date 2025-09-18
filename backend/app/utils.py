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

- "config": chart configuration strictly following ApexCharts format

  * Config must include **all details needed by ApexCharts** to directly render the chart.

  * Config must use real column names from the dataset and provide full structure (x, y, series, labels, values, etc.)
 
### 2. Chart Generation Rules

- You MUST generate every chart type from the ApexCharts supported list that can be meaningfully constructed from the dataset.

- For each chart type, if the dataset contains enough matching columns, you MUST output a valid config.

- Do not skip or omit any chart type just because another chart type already represents similar data.

- Even if multiple charts visualize similar aspects, you MUST still include them all, as long as they are valid ApexCharts charts for the dataset.

- Always suggest at least 2 visually meaningful chart types based on the dataset.

- Only suggest "table" if no other chart type can meaningfully represent the data.

- Never produce extra commentary; output only valid JSON.
 
### 3. Chart Config Rules
 
- Trend/Time-Series: 'line','area'

  {

    "x":"date_col",

    "series":[{"name":"Metric","y":"value_col"}],

    "markers":{"size":5}

  }
 
- Comparison/Ranking: 'bar','radar'

  {

    "x":"category_col",

    "series":[{"name":"Metric","y":"value_col"}]

  }
 
- Composition/Proportion: 'pie','donut','polarArea','radialBar'

  {

    "labels":["cat1","cat2",...],

    "series":[val1,val2,...]

  }

  RULES:

    * Only suggest these chart types if the query requests top N categories AND N ≤ 5.

    * Always use exactly top N rows returned by the query.

    * Do NOT calculate or include any "Other" slice.

    * Total slices = top N rows only.
 
- Distribution: 'histogram','boxPlot'

  {

    "x":"num_col",

    "series":[{"name":"Count","y":"count_col"}]

  }
 
- Relationship: 'scatter','bubble'

  {

    "x":"metric1",

    "y":"metric2",

    "size":"metric3_optional"

  }
 
- Hierarchical/Matrix: 'heatmap','treemap'

  {

    "x":"cat1",

    "y":"cat2",

    "values":[...]

  }
 
- Range/Stock: 'rangeBar','candlestick'

  {

    "x":"date_or_cat",

    "series":[{"name":"Metric","y":["low","high"]}]

  }
 
- Table (last resort): 'table'

  {

    "columns":["col1","col2",...]

  }
 
### 4. Strict Rules

- Always return strictly valid JSON only; no explanations, no extra text.

- Do NOT calculate or include any "Other" slice for Pie/Donut/PolarArea/RadialBar.

- Strictly include ALL suitable ApexCharts chart types that the dataset can support.

- “Suitable” means: if the dataset has the minimum required columns for that chart type (e.g., time + numeric for line, 2+ numerics for scatter, category + numeric for bar), then you MUST output it.

- Numeric values must be taken exactly from the dataset, never estimated.

- Line/Area charts must include markers to show individual points.

- Do not truncate, skip, or limit the number of points, labels, or series.

"""

 
    # Identify column types for better LLM hints
    column_info = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        is_numeric = pd.api.types.is_numeric_dtype(df[col])
        is_datetime = pd.api.types.is_datetime64_any_dtype(df[col])
        is_categorical = not is_numeric and df[col].nunique() < min(len(df), 20)

        column_info.append({
            "name": col,
            "type": dtype,
            "is_numeric": is_numeric,
            "is_datetime": is_datetime,
            "is_categorical": is_categorical,
            "unique_values": df[col].nunique()
        })

    logger.debug(f"User prompt for chart LLM:\n{system_prompt}")

    logger.info("Calling LLM for chart suggestion...")
    try:
        llm_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Given the question: '{question}' and data with columns {list(df.columns)}, suggest chart types and configurations."}
            ],
            temperature=0.3, 
            response_format={"type": "json_object"}
        )
        response_content = llm_response.choices[0].message.content
        chart_suggestion = json.loads(response_content)

        # Enrich config with raw data for frontend
        for chart in chart_suggestion.get("charts", []):
            chart['config']['data'] = df.to_dict(orient="records")
            chart['config']['columns'] = list(df.columns)
            chart['config']['original_question'] = question

        return chart_suggestion
    except Exception as e:
        print(f"Error generating chart suggestion from LLM: {e}")
        return {
            "title": question,
            "charts": [
                {
                    "chart_type": "table",
                    "config": {
                        "data": df.to_dict(orient="records"),
                        "columns": list(df.columns),
                        "original_question": question
                    }
                }
            ]
        }
