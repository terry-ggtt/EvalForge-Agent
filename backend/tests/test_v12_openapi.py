from app.main import (
    create_app,
)


def test_v12_openapi_contains_core_endpoints():

    app = create_app()

    schema = app.openapi()

    paths = schema[
        "paths"
    ]

    assert (
        "/health"
        in paths
    )

    assert (
        "/experiments"
        in paths
    )

    assert (
        "/experiments/run"
        in paths
    )

    assert (
        "/runs"
        in paths
    )

    assert (
        "/runs/{run_id}"
        in paths
    )

    assert (
        "/runs/{run_id}/timeline"
        in paths
    )

    assert (
        "/comparisons/experiments"
        in paths
    )

    assert (
        "/gates/evaluate"
        in paths
    )