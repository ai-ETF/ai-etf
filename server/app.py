from fastapi import FastAPI

from server.api import ask, upload

app = FastAPI(title="ETF RAG Server")

app.include_router(upload.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
