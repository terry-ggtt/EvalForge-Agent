"""Read-only showcase definitions; Job creation/execution continue through the existing async APIs."""
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends
from app.api.dependencies import get_evaluation_job_store
from app.jobs.store import EvaluationJobStore

router = APIRouter(prefix="/showcase", tags=["showcase"])


@router.get("/business-agent")
def business_agent_showcase() -> dict:
    """Return curated source-span labels and active adapter name; never return bridge credentials."""
    path = Path(__file__).resolve().parents[1] / "showcase/business_agent.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))
    return {**dataset, "adapter": os.environ.get("HARNESS_AGENT_KIND", "demo")}

@router.get("/business-agent/latest")
async def latest_business_agent_showcase(
    store: EvaluationJobStore = Depends(get_evaluation_job_store),
) -> dict:
    """Return most recent explicitly linked pair among 100 jobs; never guess pair identity from names."""
    page = await store.search(limit=100, offset=0)
    for job in page.items:
        metadata = job.payload.metadata
        baseline_id = metadata.get("baseline_job_id")
        if metadata.get("showcase") != "business-agent" or not isinstance(baseline_id, str):
            continue
        baseline = await store.get(baseline_id)
        if (
            baseline is not None
            and baseline.payload.metadata.get("showcase") == "business-agent"
            and baseline.payload.dataset_version == job.payload.dataset_version
            and baseline.payload.metadata.get("corpus_sha256") == metadata.get("corpus_sha256")
        ):
            return {"baseline": baseline_id, "candidate": job.job_id}
    return {"baseline": None, "candidate": None}
