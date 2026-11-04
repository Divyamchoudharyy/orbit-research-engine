from fastapi import APIRouter
router = APIRouter()

## Health check endpoint__ Useful for monitoring and ensuring the API is running smoothly.
@router.get("/health")
def health_check():
    return {"status": "ok","version": "1.0.0"}