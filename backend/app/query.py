import json
import pandas as pd
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from .config import engine
from .utils import get_sql_from_llm, get_chart_suggestion_from_llm

router = APIRouter()


class QueryRequest(BaseModel):
    dataset_id: str = Field(
        ..., description="The unique ID of the dataset to query.")
    question: str = Field(
        ..., description="The natural language question from the user.")


class ChartSuggestion(BaseModel):
    chart_type: str
    reasoning: str


class QueryResponse(BaseModel):
    dataset_id: str
    sql_query: str
    chart_suggestion: ChartSuggestion
    results: List[Dict[str, Any]]


@router.post("/query", response_model=QueryResponse, tags=["Query"])
async def run_query(request: QueryRequest) -> QueryResponse:
    """
    Takes a natural language question and a dataset_id, generates and executes
    a SQL query,and returns the results along with a chart suggestion.
    """
    try:
        with engine.connect() as conn:
            # 1. Fetch metadata for the given dataset
            result = conn.execute(text(
                "SELECT schema_name, table_metadata FROM dataset_metadata "
                "WHERE dataset_id = :id"
            ), {"id": request.dataset_id}).fetchone()

            if not result:
                raise HTTPException(
                    status_code=404,
                    detail=f"Dataset with ID '{request.dataset_id}' not found")

            schema_name, metadata = result
            metadata = json.loads(metadata) if isinstance(metadata, str) else metadata

            # 2. Use utility function to generate the SQL query
            sql_query = get_sql_from_llm(
                metadata, schema_name, request.question)

            # 3. Execute the generated SQL query
            results_df = pd.read_sql(text(sql_query), conn)

            # 4. Use utility function to suggest a chart type
            chart_suggestion_dict = get_chart_suggestion_from_llm(
                                            request.question, results_df)

    except ValueError as e:
        # Catches errors raised from our utility functions (e.g., LLM failures)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        # Catches other potential errors (e.g., failed SQL execution)
        raise HTTPException(status_code=400,
                            detail=f"An error occurred during query"
                                   f"execution: {str(e)}")

    # 5. Assemble and return the final, validated response
    return QueryResponse(
        dataset_id=request.dataset_id,
        sql_query=sql_query,
        chart_suggestion=ChartSuggestion(**chart_suggestion_dict),
        results=results_df.to_dict(orient="records")
    )
