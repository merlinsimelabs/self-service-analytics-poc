import os
import zipfile
import tempfile
import pandas as pd
import shutil
from uuid import uuid4
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from .config import engine
from .utils import save_schema_metadata, get_schema_from_llm
from sqlalchemy import text
router = APIRouter()


@router.post("/upload-zip")
async def upload_zip(
    file: UploadFile = File(...),
    catalog: str = Form(...)
):
    """
    Uploads a ZIP of CSV/XLSX files, uses an LLM to infer the schema based on
    a user-provided catalog, stores data in PostgreSQL, and saves the metadata.
    """
    if not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=400, detail="File must be a ZIP archive.")

    if not catalog:
        raise HTTPException(
            status_code=400, detail="A catalog description is required.")

    dataset_id = str(uuid4())
    schema_name = f"dataset_{dataset_id.replace('-', '_')}"

    # Create new schema in the database
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema_name}"))
        conn.commit()

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, file.filename)
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(tmpdir)

        tables_dfs = {}
        # Process each file and load it into the database
        for fname in os.listdir(tmpdir):
            fpath = os.path.join(tmpdir, fname)
            if not os.path.isfile(fpath) or fname.startswith('__MACOSX'):
                continue

            if fname.endswith(".csv"):
                df = pd.read_csv(fpath)
            elif fname.endswith(".xlsx"):
                df = pd.read_excel(fpath)
            else:
                continue

            table_name = os.path.splitext(fname)[0].lower().replace(" ", "_")
            tables_dfs[table_name] = df

            # Store table in PostgreSQL
            df.to_sql(
                table_name,
                engine,
                schema=schema_name,
                if_exists="replace",
                index=False
            )

        if not tables_dfs:
            raise HTTPException(
                status_code=400, detail="No valid CSV or XLSX"
                                        "files found in the ZIP.")

        # Use LLM to generate the schema metadata
        try:
            full_metadata = get_schema_from_llm(tables_dfs, catalog)
        except ValueError as e:
            raise HTTPException(status_code=500, detail=str(e))

        # Save the generated metadata to the database
        save_schema_metadata(engine, dataset_id, schema_name, full_metadata)

    return {
        "message": "Dataset uploaded and schema generated successfully.",
        "dataset_id": dataset_id,
        "schema_name": schema_name,
        "metadata": full_metadata
    }
