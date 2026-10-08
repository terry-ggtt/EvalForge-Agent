"""HTTP-facing schemas.

The canonical harness contracts live in app.harness.contracts. Re-exporting the
public request/response models here keeps API imports simple without duplicating
model definitions.
"""

from app.harness.contracts import CaseResult, EvaluationReport, TestCase
from pydantic import BaseModel


class EvaluationRequest(BaseModel):
    cases: list[TestCase]


EvaluationResponse = EvaluationReport

__all__ = [
    "CaseResult",
    "EvaluationRequest",
    "EvaluationResponse",
    "TestCase",
]
