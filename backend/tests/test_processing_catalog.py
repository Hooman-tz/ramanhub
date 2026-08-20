"""Tests for `GET /processing/algorithms`, the catalog the frontend's
pipeline builder renders from. No DB needed — the catalog is served straight
from the code-side registry."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.processing.algorithms.registry import ALGORITHM_SPECS
from app.routers import processing

app = FastAPI()
app.include_router(processing.router)
client = TestClient(app)


def _catalog() -> dict:
    resp = client.get("/processing/algorithms")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_catalog_lists_every_registered_algorithm():
    body = _catalog()

    assert {a["step_type"] for a in body["algorithms"]} == {
        spec.step_type for spec in ALGORITHM_SPECS
    }


def test_catalog_is_public():
    """Which preprocessing steps exist is part of deciding whether to sign
    up, and reveals no user data."""
    assert client.get("/processing/algorithms").status_code == 200


def test_algorithms_are_ordered_by_pipeline_category():
    body = _catalog()

    positions = [body["categories"].index(a["category"]) for a in body["algorithms"]]
    assert positions == sorted(positions)
    assert body["categories"][0] == "despiking"  # spikes must be removed first


def test_each_entry_carries_what_the_ui_needs_to_render_a_form():
    body = _catalog()

    for algorithm in body["algorithms"]:
        assert algorithm["label"]
        assert algorithm["description"]
        assert algorithm["version"]
        assert isinstance(algorithm["param_schema"], dict)
        assert isinstance(algorithm["transforms_axis"], bool)


def test_axis_changing_steps_are_flagged_for_the_ui():
    body = _catalog()

    flagged = {a["step_type"] for a in body["algorithms"] if a["transforms_axis"]}
    assert flagged == {"raman.crop", "raman.resample"}


def test_param_schemas_declare_titles_for_their_properties():
    """The builder renders one labelled input per property; an untitled
    property would surface as a raw key like `min_prominence_ratio`."""
    body = _catalog()

    for algorithm in body["algorithms"]:
        for key, prop in algorithm["param_schema"].get("properties", {}).items():
            assert prop.get("title"), f"{algorithm['step_type']}.{key} has no title"
