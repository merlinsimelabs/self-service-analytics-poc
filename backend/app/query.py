import json
import logging
import pandas as pd
import numpy as np
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .config import engine
from .utils import get_sql_from_llm, get_chart_suggestion_from_llm


router = APIRouter()


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    dataset_id: str
    question: str


@router.post("/query", tags=["Query"])
async def run_query(request: QueryRequest):
    """
    Takes a natural language question and a dataset_id,
    generates and executes a SQL query,
    and returns results along with a chart suggestion.
    """
    logger.info(f"Received query request for dataset_id: {request.dataset_id}")

    try:
        with engine.connect() as conn:
            logger.info("Fetching schema metadata from database...")
            stmt = text(
                "SELECT schema_name, table_metadata FROM dataset_metadata WHERE dataset_id = :id"
            )
            result = conn.execute(stmt, {"id": request.dataset_id}).fetchone()

            if not result:
                logger.warning(f"Dataset with ID '{request.dataset_id}' not found.")
                raise HTTPException(status_code=404, detail=f"Dataset with ID '{request.dataset_id}' not found.")

            schema_name, raw_table_metadata = result 
            
            if isinstance(raw_table_metadata, (str, bytes, bytearray)):
                try:
                    metadata = json.loads(raw_table_metadata)
                    logger.debug(f"Successfully loaded metadata (from string) for schema '{schema_name}': {json.dumps(metadata, indent=2)}")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse table_metadata JSON for dataset '{request.dataset_id}': {e}", exc_info=True)
                    raise HTTPException(status_code=500, detail="Corrupted schema metadata found in database.")
            elif isinstance(raw_table_metadata, dict):
                metadata = raw_table_metadata
                logger.debug(f"Successfully loaded metadata (as dict directly) for schema '{schema_name}': {json.dumps(metadata, indent=2)}")
            else:
                logger.error(f"Unexpected type for table_metadata: {type(raw_table_metadata)}. Expected str or dict.")
                raise HTTPException(status_code=500, detail="Unexpected format for schema metadata in database.")
           
            logger.info("Calling LLM to generate SQL query...")
            
            sql_query = get_sql_from_llm(metadata, schema_name, request.question)
            logger.debug(f"Generated SQL Query:\n{sql_query}")

            
            logger.info("Executing SQL query against the database...")
            results_df = pd.read_sql(text(sql_query), conn)
            logger.info(f"Query executed successfully, {len(results_df)} rows returned.")
            logger.debug(f"Raw DataFrame head:\n{results_df.head().to_string()}")

            
            results_df_for_json = results_df.copy()
            
            results_df_for_json.replace([np.inf, -np.inf], np.nan, inplace=True)
            results_df_for_json = results_df_for_json.where(pd.notnull(results_df_for_json), None)
            logger.debug(f"Cleaned DataFrame for JSON (head):\n{results_df_for_json.head().to_string()}")

            
            logger.info("Calling LLM to generate chart suggestions...")
            chart_suggestion_dict = {}
            try:
                chart_suggestion_dict = get_chart_suggestion_from_llm(
                    request.question, results_df
                )
                logger.info("Chart suggestions generated.")
                logger.debug(f"Generated chart suggestion: {json.dumps(chart_suggestion_dict, indent=2)}")
            except Exception as chart_err:
                logger.error(f"Error generating chart suggestion: {chart_err}", exc_info=True)
                chart_suggestion_dict = {
                    "title": request.question,
                    "charts": [
                        {"chart_type": "table", "config": {"columns": list(results_df.columns)}}
                    ]
                }
                logger.warning("Falling back to table chart suggestion due to an error in LLM chart generation.")


        # Return Response
        return {
            "status": 200,
            "data_status": "success",
            "message": "Query executed successfully.",
            "data": {
                "dataset_id": request.dataset_id,
                "sql_query": sql_query,
                "chart_suggestion": chart_suggestion_dict,
                "results": results_df_for_json.to_dict(orient="records"),
            }
        }

    except ValueError as e:
        logger.error(f"ValueError during LLM processing: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))

    except SQLAlchemyError as e:
        logger.error(f"Database error during query execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"A database error occurred: {e}")

    except Exception as e:
        logger.error(f"An unexpected internal error occurred: {e}", exc_info=True)
        
        detail_message = str(e)
        raise HTTPException(status_code=500, detail=f"An unexpected internal error occurred: {detail_message}")