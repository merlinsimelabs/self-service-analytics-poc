from sqlalchemy import text
from fastapi import APIRouter
from .config import engine
from .utils import UniformResponse
from typing import List
from pydantic import BaseModel


router = APIRouter()


class DatasetInfo(BaseModel):
    dataset_id: str
    user_defined_name: str


@router.get("/datasets", response_model=List[DatasetInfo], tags=["Datasets"])
async def get_datasets():
    """
    Retrieves a list of all uploaded datasets to be displayed in the UI.
    It returns the user-defined name for display and the unique
    dataset_id for querying.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT dataset_id, user_defined_name, schema_name "
                     "FROM dataset_metadata ORDER BY "
                     "created_at DESC")
            )
            datasets = [
                {
                    "id": row.dataset_id,
                    "name": row.user_defined_name,
                    "schema": row.schema_name
                }
                for row in result
            ]

        return UniformResponse(
            data=datasets if datasets else [],
            status=200,
            message="Datasets fetched successfully." if datasets else
                    "No datasets available.",
            data_status="success"
        )

    except Exception as e:
        return UniformResponse(
            error={"code": "INTERNAL_SERVER_ERROR", "details": [str(e)]},
            status=500,
            message="An unexpected error occurred while fetching datasets.",
            data_status="failure"
        )
