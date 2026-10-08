from fastapi import FastAPI

from fastapi.testclient import (
    TestClient,
)

from app.api.errors import (
    register_exception_handlers,
)

from app.api.runs import (
    router as runs_router,
)

from app.harness.replay import (
    RunNotFoundError,
)


class FakeReplayService:

    async def load(
        self,
        run_id: str,
    ):

        raise RunNotFoundError(
            f"Run not found: {run_id}"
        )

    async def timeline(
        self,
        run_id: str,
    ):

        raise RunNotFoundError(
            f"Run not found: {run_id}"
        )


def test_missing_run_returns_standard_404():

    app = FastAPI()

    register_exception_handlers(
        app
    )

    app.state.run_replay_service = (
        FakeReplayService()
    )

    app.include_router(
        runs_router
    )

    client = TestClient(
        app
    )

    response = client.get(
        "/runs/not-found"
    )

    assert (
        response.status_code
        == 404
    )

    body = response.json()

    assert (
        body["error"]["code"]
        == "run_not_found"
    )

    assert (
        body["error"]["message"]
        == "Run not found: not-found"
    )

from app.api.comparisons import (
    router as comparisons_router,
)

from app.harness.experiment_comparison_service import (
    ExperimentComparisonError,
)


class FakeComparisonService:

    async def compare(
        self,
        **kwargs,
    ):

        raise ExperimentComparisonError(
            "Dataset versions differ."
        )


def test_comparison_conflict_returns_409():

    app = FastAPI()

    register_exception_handlers(
        app
    )

    app.state.experiment_comparison_service = (
        FakeComparisonService()
    )

    app.include_router(
        comparisons_router
    )

    client = TestClient(
        app
    )

    response = client.post(
        "/comparisons/experiments",

        json={
            "baseline_experiment_id":
                "baseline",

            "candidate_experiment_id":
                "candidate",

            "require_same_dataset_version":
                True,
        },
    )

    assert (
        response.status_code
        == 409
    )

    assert (
        response.json()
        ["error"]
        ["code"]
        ==
        "experiment_comparison_conflict"
    )

from app.api.experiment_execution import (
    router as execution_router,
)


class FakeExperimentRunner:
    pass


def test_validation_error_uses_standard_contract():

    app = FastAPI()

    register_exception_handlers(
        app
    )

    app.state.experiment_runner = (
        FakeExperimentRunner()
    )

    app.include_router(
        execution_router
    )

    response = TestClient(
        app
    ).post(
        "/experiments/run",

        json={
            "name":
                "",

            "dataset_version":
                "dataset-v1",

            "agent_version":
                "agent-v1",

            "cases":
                [],
        },
    )

    assert (
        response.status_code
        == 422
    )

    body = response.json()

    assert (
        body["error"]["code"]
        == "validation_error"
    )

    assert (
        isinstance(
            body["error"]["details"],
            list,
        )
    )

class BrokenExperimentRunner:

    async def run(
        self,
        **kwargs,
    ):
        raise RuntimeError(
            "database password=secret"
        )


def test_internal_error_is_sanitized():

    app = FastAPI()

    register_exception_handlers(
        app
    )

    app.state.experiment_runner = (
        BrokenExperimentRunner()
    )

    app.include_router(
        execution_router
    )

    client = TestClient(
        app,
        raise_server_exceptions=False,
    )

    response = client.post(
        "/experiments/run",

        json={
            "name":
                "test",

            "dataset_version":
                "dataset-v1",

            "agent_version":
                "agent-v1",

            "cases": [
                {
                    "id":
                        "case-1",

                    "input_text":
                        "hello",

                    "expected_output":
                        "hello",
                }
            ],
        },
    )

    assert (
        response.status_code
        == 500
    )

    body = response.json()

    assert (
        body["error"]["code"]
        == "internal_error"
    )

    assert (
        body["error"]["message"]
        ==
        "Internal server error."
    )

    assert (
        "secret"
        not in response.text
    )