"""Saved graph edits have an owner and current evidence permissions."""

import pytest
from fastapi.testclient import TestClient

from hippo.web.app import create_app


def test_saved_draft_cannot_be_read_or_applied_after_evidence_revocation(ctx):
    from hippo.access import Access
    from hippo.hipporag.indexer import Chunk, index_source
    from hippo.knowledge.changeset_access import ChangesetAccess, ChangesetUnavailable

    ctx.store.ensure_roles()
    owner = ctx.store.create_user("draft-owner", "secret1", "individual")
    access = Access(rank=0, user_id=owner)
    source = ctx.store.create_source("text", "Public")
    index_source(ctx.store, ctx.ollama, source, [Chunk(0, "Title", "Orion was designed by Mira.")])
    entity = next(iter(ctx.graph_for(access).entity_names))
    identity = ChangesetAccess(ctx, access).save(
        "Evidence edit", [{"op": "set_node_boost", "entity_id": entity, "boost": 1.5}]
    )
    assert ChangesetAccess(ctx, access).get(identity) is not None
    ctx.store.set_source_access(source, "local-admin")
    service = ChangesetAccess(ctx, access)
    assert service.get(identity) is None
    assert service.list() == []
    with pytest.raises(ChangesetUnavailable):
        service.apply(identity)
    assert ctx.store.get_changeset(identity)["status"] == "draft"


def test_failed_ownership_write_rolls_back_the_draft_and_epoch(ctx, monkeypatch):
    from hippo.access import Principal
    from hippo.knowledge.changeset_access import ChangesetAccess

    service = ChangesetAccess(ctx, Principal.open().access)
    epoch = ctx.store.authorization_epoch()
    original = ctx.store.set_meta

    def fail_owner(key, value):
        if key.startswith("changeset_owner:"):
            raise RuntimeError("ownership write failed")
        return original(key, value)

    monkeypatch.setattr(ctx.store, "set_meta", fail_owner)
    with pytest.raises(RuntimeError, match="ownership write failed"):
        service.save("Atomic draft", [{"op": "set_setting", "name": "damping", "value": 0.7}])
    assert ctx.store.list_changesets() == []
    assert ctx.store.authorization_epoch() == epoch


def test_changeset_response_omits_global_graph_counter(ctx):
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        saved = client.post(
            "/api/changesets",
            json={"name": "Tuning", "ops": [{"op": "set_setting", "name": "damping", "value": 0.7}]},
        )
        response = client.post("/api/changesets/" + saved.json()["changeset_id"] + "/apply")
        assert response.status_code == 200
        assert "graph_version" not in response.json()


@pytest.mark.parametrize("operation", ["list", "apply", "delete"])
def test_changeset_routes_do_not_expose_or_modify_another_users_draft(ctx, operation):
    ctx.store.ensure_roles()
    ctx.store.create_user("owner", "secret1", "arch-admin")
    ctx.store.create_user("outsider", "secret2", "arch-admin")
    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        client.post("/login", data={"username": "owner", "password": "secret1"})
        saved = client.post(
            "/api/changesets",
            json={
                "name": "SECRET DRAFT",
                "note": "SECRET NOTE",
                "ops": [{"op": "set_setting", "name": "damping", "value": 0.7}],
            },
        )
        assert saved.status_code == 200
        identity = saved.json()["changeset_id"]
        client.post("/logout")
        client.post("/login", data={"username": "outsider", "password": "secret2"})
        if operation == "list":
            response = client.get("/api/changesets")
            assert response.status_code == 200
            assert response.json() == []
        elif operation == "apply":
            response = client.post("/api/changesets/" + identity + "/apply")
            assert response.status_code == 404
        else:
            response = client.delete("/api/changesets/" + identity)
            assert response.status_code == 404
        assert "SECRET" not in response.text
        assert ctx.store.get_changeset(identity) is not None
