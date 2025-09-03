import json
import logging
import pandas as pd
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .config import engine
from .utils import get_sql_from_llm, get_chart_suggestion_from_llm


router = APIRouter()


class QueryRequest(BaseModel):
    dataset_id: str
    question: str
   # catalog: Optional[str] = None # Keep this commented out if you don't want to pass it


@router.post("/query", tags=["Query"])
async def run_query(request: QueryRequest):
    """
    Takes a natural language question and a dataset_id,
    generates and executes a SQL query,
    and returns results along with a chart suggestion.
    """
    logging.info(f"Received query request for dataset_id: {request.dataset_id}")

    try:
        with engine.connect() as conn:

            logging.info("Fetching schema metadata from database...")
            stmt = text(
                "SELECT schema_name, table_metadata FROM dataset_metadata WHERE dataset_id = :id"
            )
            result = conn.execute(stmt, {"id": request.dataset_id}).fetchone()

            if not result:
                logging.warning(f"Dataset with ID '{request.dataset_id}' not found.")
                raise HTTPException(status_code=404, detail=f"Dataset with ID '{request.dataset_id}' not found.")

            schema_name, metadata = result

            metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
            logging.info(f"Successfully fetched metadata for schema: {schema_name}")


            # --- CHANGE IS HERE ---
            # Remove request.catalog as it's not part of QueryRequest and you don't want to pass it.
            sql_query = get_sql_from_llm(metadata, schema_name, request.question)


            logging.info(f"Generated SQL Query:\n{sql_query}")

            logging.info("Executing SQL query against the database...")
            results_df = pd.read_sql(text(sql_query), conn)
            # logging.info(f"Query executed successfully, {len(results_df)} rows returned.")


            # chart_suggestion_dict = get_chart_suggestion_from_llm(
            #     request.question, results_df
            # )
            logging.info(f"Query executed successfully, {len(results_df)} rows returned.")

            # Replace NaN/Infinity with None so JSON serialization works
            results_df = results_df.where(pd.notnull(results_df), None)

            chart_suggestion_dict = get_chart_suggestion_from_llm(
            request.question, results_df
                )


        return {
            "status": 200,
            "data_status": "success",
            "message": "Query executed successfully.",
            "data": {
                "dataset_id": request.dataset_id,
                "sql_query": sql_query,
                "chart_suggestion": chart_suggestion_dict,
                "results": results_df.to_dict(orient="records"),
            }
        }

    except ValueError as e:

        logging.error(f"ValueError during query execution: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except SQLAlchemyError as e:

        logging.error(f"Database error during query execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"A database error occurred: {e}")

    except Exception as e:

        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected internal error occurred: {e}")