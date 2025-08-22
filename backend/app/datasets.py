from sqlalchemy import text
from fastapi import APIRouter
from .config import engine
from .utils import UniformResponse

router = APIRouter()


@router.get("/datasets")
async def get_datasets():
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT dataset_id, user_defined_name, schema_name "
                     "FROM dataset_metadata")
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
