"""Read-only available evaluator discovery; imports never originate from HTTP selections."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from evalforge_evaluator_sdk import EvaluatorManifest, RegistrationSource
from app.evaluator.catalog import EvaluatorCatalog
from app.evaluator.contracts import EvaluatorSelectionError
from app.schemas.errors import STANDARD_ERROR_RESPONSES


class EvaluatorDescriptor(BaseModel):
    """Public producer and config-schema metadata, excluding task config and import paths."""

    manifest: EvaluatorManifest
    source: RegistrationSource
    config_schema: dict[str, Any]


router = APIRouter(prefix="/evaluators", tags=["evaluators"])


def get_evaluator_catalog(request: Request) -> EvaluatorCatalog:
    """Return the process-start catalogue from request.app; fail 503 rather than importing on demand."""
    catalog = getattr(request.app.state, "evaluator_catalog", None)
    if catalog is None:
        raise HTTPException(status_code=503, detail="Evaluator catalogue unavailable")
    return catalog


@router.get("", response_model=list[EvaluatorDescriptor], responses=STANDARD_ERROR_RESPONSES)
async def list_evaluators(catalog: EvaluatorCatalog = Depends(get_evaluator_catalog)) -> list[dict]:
    """Return available validated evaluator identities/config schemas from catalog; never execute scores."""
    return catalog.list()


async def evaluator_selection_error(request: Request, exc: EvaluatorSelectionError) -> JSONResponse:
    """Render exc's safe code using request's existing API error envelope; no config contents are exposed."""
    return JSONResponse(status_code=422, content={"error": {"code": exc.code,
        "message": "Evaluator selection or configuration is invalid.", "details": None}})
