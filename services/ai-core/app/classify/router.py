"""Classification HTTP API (Feature 08)."""

from fastapi import APIRouter

from app.classify.classifier import ClassifyRequest, classify

router = APIRouter()


@router.post("/api/v1/internal/classify")
async def classify_complaint(req: ClassifyRequest) -> dict:
    return classify(req.text)
