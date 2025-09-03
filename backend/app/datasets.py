from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from .config import engine

router = APIRouter()


class DatasetInfo(BaseModel):
    dataset_id: str
    user_defined_name: str


@router.get("/datasets", response_model=List[DatasetInfo], tags=["Datasets"])
async def get_all_datasets():
    """
    Retrieves a list of all uploaded datasets to be displayed in the UI.
    It returns the user-defined name for display and the unique
    dataset_id for querying.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT dataset_id, user_defined_name FROM dataset_metadata "
                "ORDER BY created_at DESC"
            )).fetchall()

            datasets = [
                {"dataset_id": row[0],
                 "user_defined_name": row[1]} for row in result
            ]
            return datasets
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while fetching datasets: {str(e)}")
