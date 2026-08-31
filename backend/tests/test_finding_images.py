"""M6.2: author-supplied Finding images (figures + graphical abstract).

Covers upload / read / patch / reorder / delete, the owner-only + read-gate
rules, the validation guards (type, size, count, dedupe), and that
`serialize_finding` surfaces `images` ordered by position.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.routers import findings

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-payload"
PNG2 = b"\x89PNG\r\n\x1a\n" + b"a-different-image"
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"fake-webp"


@pytest.fixture()
def store(monkeypatch):
    """In-memory object store patched into the findings router, so tests
    never touch a real MinIO/S3 endpoint or the local storage dir."""
    blobs: dict[tuple[str, str], bytes] = {}

    def upload_bytes(bucket, key, data, content_type=None):
        blobs[(bucket, key)] = data

    def download_bytes(bucket, key):
        return blobs[(bucket, key)]

    def object_exists(bucket, key):
        return (bucket, key) in blobs

    monkeypatch.setattr("app.routers.findings.upload_bytes", upload_bytes)
    monkeypatch.setattr("app.routers.findings.download_bytes", download_bytes)
    monkeypatch.setattr("app.routers.findings.object_exists", object_exists)
    return blobs


@pytest.fixture()
def client(db_session, store):
    app = FastAPI()
    app.include_router(findings.router)

    current: dict[str, object] = {"user": None}

    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    c = TestClient(app)
    c.set_current_user = lambda u: current.__setitem__("user", u)
    return c


def _make_finding(client, title="img thread"):
    resp = client.post("/v1/findings", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _upload(client, fid, content=PNG, content_type="image/png", kind="figure", caption=None):
    data = {"kind": kind}
    if caption is not None:
        data["caption"] = caption
    return client.post(
        f"/v1/findings/{fid}/images",
        files={"file": ("fig.png", content, content_type)},
        data=data,
    )


def test_upload_and_fetch_png(client, make_user, store):
    author = make_user()
    client.set_current_user(author)
    fid = _make_finding(client)

    resp = _upload(client, fid, caption="Figure 1")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "figure"
    assert body["caption"] == "Figure 1"
    assert body["position"] == 0
    assert body["content_type"] == "image/png"
    assert body["url"] == f"/v1/findings/{fid}/images/{body['id']}/file"
    assert len(store) == 1

    file_resp = client.get(body["url"])
    assert file_resp.status_code == 200
    assert file_resp.content == PNG
    assert file_resp.headers["content-type"] == "image/png"
    assert "immutable" in file_resp.headers["cache-control"]


def test_non_owner_cannot_upload(client, make_user):
    author, stranger = make_user(), make_user()
    client.set_current_user(author)
    fid = _make_finding(client)

    client.set_current_user(stranger)
    resp = _upload(client, fid)
    assert resp.status_code == 404


def test_file_read_gate(client, make_user):
    author, stranger = make_user(), make_user()
    client.set_current_user(author)
    fid = _make_finding(client)
    url = _upload(client, fid).json()["url"]

    # stranger can't read a draft finding's image
    client.set_current_user(stranger)
    assert client.get(url).status_code == 404
    # anonymous can't either
    client.set_current_user(None)
    assert client.get(url).status_code == 404
    # owner can
    client.set_current_user(author)
    assert client.get(url).status_code == 200


def test_rejects_bad_type_and_bad_kind(client, make_user):
    author = make_user()
    client.set_current_user(author)
    fid = _make_finding(client)

    gif = _upload(client, fid, content=b"GIF89a", content_type="image/gif")
    assert gif.status_code == 422

    bad_kind = _upload(client, fid, kind="banner")
    assert bad_kind.status_code == 422


def test_rejects_oversized(client, make_user, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    author = make_user()
    client.set_current_user(author)
    fid = _make_finding(client)

    big = b"\x89PNG\r\n\x1a\n" + b"x" * (1024 * 1024 + 10)
    resp = _upload(client, fid, content=big)
    assert resp.status_code in (413, 422)


def test_dedupe_returns_same_row(client, make_user, store):
    author = make_user()
    client.set_current_user(author)
    fid = _make_finding(client)

    first = _upload(client, fid).json()
    second = _upload(client, fid, caption="ignored on dupe").json()
    assert first["id"] == second["id"]
    assert first["position"] == second["position"]
    assert len(store) == 1


def test_twelve_image_cap(client, make_user):
    author = make_user()
    client.set_current_user(author)
    fid = _make_finding(client)

    for i in range(12):
        payload = b"\x89PNG\r\n\x1a\n" + f"image-{i}".encode()
        assert _upload(client, fid, content=payload).status_code == 201

    payload = b"\x89PNG\r\n\x1a\n" + b"image-13"
    resp = _upload(client, fid, content=payload)
    assert resp.status_code in (409, 422)


def test_patch_caption_and_reorder(client, make_user):
    author = make_user()
    client.set_current_user(author)
    fid = _make_finding(client)

    a = _upload(client, fid, content=b"\x89PNG\r\n\x1a\nAAA").json()
    b = _upload(client, fid, content=b"\x89PNG\r\n\x1a\nBBB").json()
    c = _upload(client, fid, content=b"\x89PNG\r\n\x1a\nCCC").json()
    assert [a["position"], b["position"], c["position"]] == [0, 1, 2]

    # caption edit
    patched = client.patch(
        f"/v1/findings/{fid}/images/{a['id']}", json={"caption": "renamed"}
    )
    assert patched.status_code == 200
    assert patched.json()["caption"] == "renamed"

    # move c to the front
    moved = client.patch(
        f"/v1/findings/{fid}/images/{c['id']}", json={"position": 0}
    )
    assert moved.status_code == 200
    assert moved.json()["position"] == 0

    order = {img["id"]: img["position"] for img in client.get(f"/v1/findings/{fid}").json()["images"]}
    assert order == {c["id"]: 0, a["id"]: 1, b["id"]: 2}

    # full reorder endpoint
    reordered = client.post(
        f"/v1/findings/{fid}/images/reorder",
        json={"image_ids": [b["id"], c["id"], a["id"]]},
    )
    assert reordered.status_code == 200
    positions = {img["id"]: img["position"] for img in reordered.json()["images"]}
    assert positions == {b["id"]: 0, c["id"]: 1, a["id"]: 2}

    # incomplete set is rejected
    assert client.post(
        f"/v1/findings/{fid}/images/reorder", json={"image_ids": [b["id"]]}
    ).status_code == 422


def test_delete_renormalizes_positions(client, make_user):
    author = make_user()
    client.set_current_user(author)
    fid = _make_finding(client)

    a = _upload(client, fid, content=b"\x89PNG\r\n\x1a\nAAA").json()
    b = _upload(client, fid, content=b"\x89PNG\r\n\x1a\nBBB").json()
    c = _upload(client, fid, content=b"\x89PNG\r\n\x1a\nCCC").json()

    resp = client.delete(f"/v1/findings/{fid}/images/{a['id']}")
    assert resp.status_code == 204

    images = client.get(f"/v1/findings/{fid}").json()["images"]
    assert [img["id"] for img in images] == [b["id"], c["id"]]
    assert [img["position"] for img in images] == [0, 1]


def test_serialize_finding_includes_ordered_images(client, make_user):
    author = make_user()
    client.set_current_user(author)
    fid = _make_finding(client)

    _upload(client, fid, content=b"\x89PNG\r\n\x1a\nAAA", kind="graphical_abstract")
    _upload(client, fid, content=WEBP, content_type="image/webp")

    images = client.get(f"/v1/findings/{fid}").json()["images"]
    assert len(images) == 2
    assert [img["position"] for img in images] == [0, 1]
    assert images[0]["kind"] == "graphical_abstract"
    assert images[1]["content_type"] == "image/webp"
