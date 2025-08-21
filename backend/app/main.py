from fastapi import FastAPI
from .upload import router as upload_router
from .query import router as query_router
from .datasets import router as datasets_router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Self-Service Analytics Platform ")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(upload_router, prefix="/api", tags=["Upload"])
app.include_router(query_router, prefix="/api", tags=["Query"])
app.include_router(datasets_router, prefix="/api", tags=["Datasets"])
