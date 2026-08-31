"""Routine CRUD-lite: create / list / delete (delete added in M6.5)."""


def _make_routine(client, name="Baseline + SNV"):
    return client.post(
        "/routines",
        json={
            "modality": "raman",
            "name": name,
            "description": None,
            "steps_template": [{"type": "raman.snv", "params": {}, "order": 0}],
        },
    )


def test_create_list_delete_routine(app_client, make_user):
    user = make_user()
    app_client.set_current_user(user)

    created = _make_routine(app_client)
    assert created.status_code == 201
    routine_id = created.json()["id"]

    listed = app_client.get("/routines")
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()] == [routine_id]

    deleted = app_client.delete(f"/routines/{routine_id}")
    assert deleted.status_code == 204
    assert app_client.get("/routines").json() == []


def test_delete_routine_not_owned_is_404(app_client, make_user):
    owner = make_user()
    app_client.set_current_user(owner)
    routine_id = _make_routine(app_client).json()["id"]

    app_client.set_current_user(make_user())
    assert app_client.delete(f"/routines/{routine_id}").status_code == 404
