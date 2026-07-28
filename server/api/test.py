from fastapi import APIRouter

router = APIRouter(prefix="/test", tags=["test"])


@router.get("/hello")
def hello():
    return {"message": "Hello World"}