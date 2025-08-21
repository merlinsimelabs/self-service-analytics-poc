import os
import zipfile
import tempfile
import pandas as pd
import shutil
import re
from uuid import uuid4
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from .config import engine
from .utils import save_schema_metadata, get_schema_from_llm
from sqlalchemy import text
router = APIRouter()


@router.post("/upload-zip")
async def upload_zip(
    file: UploadFile = File(...),
    catalog: str = Form(...),
    user_defined_name: str = Form(...)
):
    user_defined_name = user_defined_name.strip()

    if not all([file, file.filename.endswith(".zip"),
                catalog, user_defined_name]):
        raise HTTPException(
            status_code=400,
            detail="File, catalog, and a dataset name are required.")

    MIN_NAME_LENGTH = 3
    MAX_NAME_LENGTH = 20
    if not (MIN_NAME_LENGTH <= len(user_defined_name) <= MAX_NAME_LENGTH):
        raise HTTPException(
            status_code=400,
            detail=f"Dataset name must be between {MIN_NAME_LENGTH} "
                   f"and {MAX_NAME_LENGTH} characters long."
        )
    if not re.match("^[A-Za-z0-9 _.-]+$", user_defined_name):
        raise HTTPException(
            status_code=400,
            detail="Dataset name can only contain letters, numbers, spaces,"
            "hyphens, underscores, and periods."
        )

    with engine.connect() as conn:
        stmt = text(
            "SELECT COUNT(*) FROM dataset_metadata "
            "WHERE user_defined_name = :name")
        if conn.execute(stmt, {"name": user_defined_name}).scalar() > 0:
            raise HTTPException(
                status_code=409,
                detail="A dataset with this name already exists.")
    dataset_id = str(uuid4())
    user_id = "default_user"

    sanitized_name = user_defined_name.lower()
    sanitized_name = re.sub(r'[\s\-.]+', '_', sanitized_name)
    sanitized_name = re.sub(r'[^a-z0-9_]', '', sanitized_name)
    if not sanitized_name:
        sanitized_name = "dataset"
    unique_suffix = dataset_id.split('-')[0]
    schema_name = f"schema_{sanitized_name}_{unique_suffix}"

    with engine.connect() as conn:
        try:
            with conn.begin():
                conn.execute(text(f"CREATE SCHEMA {schema_name}"))

                with tempfile.TemporaryDirectory() as tmpdir:
                    zip_path = os.path.join(tmpdir, file.filename)
                    with open(zip_path, "wb") as buffer:
                        shutil.copyfileobj(file.file, buffer)

                    with zipfile.ZipFile(zip_path, "r") as zip_ref:
                        zip_ref.extractall(tmpdir)

                    tables_dfs = {}
                    for fname in os.listdir(tmpdir):
                        fpath = os.path.join(tmpdir, fname)
                        is_ignorable = (
                            not os.path.isfile(fpath) or
                            fname.startswith('__MACOSX')
                        )
                        if is_ignorable:
                            continue
                        if fname.endswith(".csv"):
                            df = pd.read_csv(fpath)
                        elif fname.endswith(".xlsx"):
                            df = pd.read_excel(fpath)
                        else:
                            continue
                        base_name = os.path.splitext(fname)[0]
                        table_name = base_name.lower().replace(" ", "_")
                        tables_dfs[table_name] = df

                        df.to_sql(
                            table_name,
                            con=conn,
                            schema=schema_name,
                            if_exists="replace",
                            index=False
                        )

                    if not tables_dfs:
                        raise HTTPException(
                            status_code=400,
                            detail="No valid CSV or XLSX files found in ZIP."
                            )

                    full_metadata = get_schema_from_llm(tables_dfs, catalog)

                    save_schema_metadata(
                        conn, dataset_id, user_id,
                        user_defined_name, schema_name, full_metadata
                    )

        except HTTPException as e:
            raise e
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"An unexpected error occurred during "
                       f"processing: {str(e)}")

    return {
        "message": f"Dataset '{user_defined_name}' uploaded successfully.",
        "dataset_id": dataset_id,
        "user_defined_name": user_defined_name
    }
