from fastapi import FastAPI

from server.api import ask, upload, test

app = FastAPI(title="ETF RAG Server")

app.include_router(upload.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(test.router, prefix="/test")


@app.get("/hello")
def hello():
    return {"message": "Hello World"}