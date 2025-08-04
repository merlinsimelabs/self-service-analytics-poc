from fastapi import FastAPI
from .upload import router as upload_router
from .query import router as query_router

app = FastAPI(title="Self-Service Analytics API")

app.include_router(upload_router)
app.include_router(query_router)
