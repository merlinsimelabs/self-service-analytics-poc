import os
import zipfile
import tempfile
import pandas as pd
import shutil
import json
from uuid import uuid4
from fastapi import APIRouter, UploadFile, File, HTTPException
from .config import engine
from .utils import save_schema_metadata, detect_relationships

router = APIRouter()


@router.post("/upload-zip")
async def upload_zip(
    file: UploadFile = File(...),
    schema_file: UploadFile = File(None)
):
    """
    Upload a ZIP containing CSV/XLSX files and optionally a schema JSON file.
    Extracts data, stores it in a new schema in PostgreSQL, and saves metadata.
    """
    if not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="File must be a ZIP"
                           )

    dataset_id = str(uuid4())
    schema_name = f"dataset_{dataset_id.replace('-', '_')}"

    # Create new schema in DB
    with engine.connect() as conn:
        conn.execute(f"CREATE SCHEMA {schema_name}")

    # Temporary directory for ZIP extraction
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, file.filename)

        # Save uploaded ZIP
        with open(zip_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Extract ZIP contents
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(tmpdir)

        table_metadata = {}
        tables_dfs = {}

        # Process each file in extracted folder
        for fname in os.listdir(tmpdir):
            fpath = os.path.join(tmpdir, fname)

            if not os.path.isfile(fpath):
                continue

            if not (fname.endswith(".csv") or fname.endswith(".xlsx")):
                continue

            table_name = os.path.splitext(fname)[0].lower()

            if fname.endswith(".csv"):
                df = pd.read_csv(fpath)
            else:
                df = pd.read_excel(fpath)

            # Store table in PostgreSQL
            df.to_sql(
                table_name,
                engine,
                schema=schema_name,
                if_exists="replace", index=False
                )

            # columns for metadata
            columns_info = [
                {"name": col, "dtype": str(df[col].dtype)}
                for col in df.columns
                ]
            table_metadata[table_name] = columns_info
            tables_dfs[table_name] = df

        # Use provided schema file if available
        if schema_file:
            try:
                schema_content = schema_file.file.read().decode("utf-8")
                user_schema = json.loads(schema_content)
                full_metadata = user_schema
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid JSON schema file"
                    )
        else:
            relationships = detect_relationships(tables_dfs)
            full_metadata = {
                "tables": table_metadata,
                "relationships": relationships
            }

        # Saving metadata to DB
        save_schema_metadata(engine, dataset_id, schema_name, full_metadata)

    return {
        "message": "Dataset uploaded and stored successfully",
        "dataset_id": dataset_id,
        "schema_name": schema_name,
        "metadata": full_metadata
    }
