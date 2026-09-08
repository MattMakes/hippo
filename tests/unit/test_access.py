"""
Access control: roles and users in the store, the Cypher predicate on every read, and the
scoped in-memory graph that keeps a search inside what the caller may see.

The same tests run against the FakeStore and (in CI) real Neo4j, so the predicate and its
in-memory mirror cannot drift apart.
"""

from __future__ import annotations

import pytest

from hippo import ask as ask_service
from hippo.access import (
    DEFAULT_ROLES,
    EVERYTHING,
    Access,
    Principal,
    hash_password,
    roles_at_or_below,
    top_role,
    verify_password,
)
from hippo.context import AppContext
from hippo.hipporag.graph_index import GraphIndex
from hippo.hipporag.indexer import Chunk, index_source
from hippo.hipporag.text import make_id

# ------------------------------------------------------------------ helpers


def sections(sample_text: str) -> list[tuple[str, str]]:
    out = []
    for section in sample_text.split("## ")[1:]:
        lines = section.splitlines()
        out.append((lines[0].strip(), "\n".join(lines[1:]).strip()))
    return out


def index_split(ctx: AppContext, sample_text: str) -> tuple[str, str]:
    """
    Two sources from the sample: the first half of its sections open to everyone, the second half
    for local admins and above. Returns (open_id, restricted_id).
    """
    ctx.store.ping()
    parts = sections(sample_text)
    half = len(parts) // 2
    open_id = ctx.store.create_source("text", "Open half")
    restricted_id = ctx.store.create_source(
        "text", "Restricted half", owner_id="boss", access_role_id="local-admin"
    )
    index_source(ctx.store, ctx.ollama, open_id, [Chunk(i, t, x) for i, (t, x) in enumerate(parts[:half])])
    index_source(
        ctx.store, ctx.ollama, restricted_id, [Chunk(i, t, x) for i, (t, x) in enumerate(parts[half:])]
    )
    return open_id, restricted_id


INDIVIDUAL = Access(rank=0, user_id="someone")
LOCAL_ADMIN = Access(rank=20, user_id="admin")
OWNER = Access(rank=0, user_id="boss")


# ------------------------------------------------------------------ the rule


def test_can_see_source_rank_owner_and_unrestricted() -> None:
    restricted = {"id": "s", "min_rank": 20, "owner_id": "boss"}
    assert not INDIVIDUAL.can_see_source(restricted)
    assert LOCAL_ADMIN.can_see_source(restricted)
    assert OWNER.can_see_source(restricted), "the owner always sees their own source"
    assert EVERYTHING.can_see_source(restricted)
    assert INDIVIDUAL.can_see_source({"id": "old"}), "a source from before roles existed is open to all"


def test_params_always_bind_the_same_three_names() -> None:
    assert set(INDIVIDUAL.params()) == {"acc_all", "acc_rank", "acc_uid"}
    assert Access(rank=3).params() == {"acc_all": False, "acc_rank": 3, "acc_uid": ""}


def test_passwords_hash_and_verify_but_never_compare_plain() -> None:
    stored = hash_password("hunter22")
    assert stored.startswith("scrypt$") and "hunter22" not in stored
    assert verify_password("hunter22", stored)
    assert not verify_password("hunter23", stored)
    assert not verify_password("hunter22", None)
    assert not verify_password("hunter22", "garbage")
    with pytest.raises(ValueError):
        hash_password("abc")


def test_principal_capabilities_and_management_rules() -> None:
    roles = {r["id"]: r for r in DEFAULT_ROLES}
    admin = Principal.for_user({"id": "u1", "username": "ann"}, roles["local-admin"])
    assert admin.can("manage_users") and not admin.can("manage_roles")
    assert admin.outranks(10) and not admin.outranks(20)
    assert admin.may_assign_role(roles["individual"]) and not admin.may_assign_role(roles["arch-admin"])
    assert admin.may_manage_source({"id": "s", "min_rank": 0, "owner_id": "x"})
    assert not admin.may_manage_source({"id": "s", "min_rank": 40, "owner_id": "x"}), (
        "cannot manage what it cannot see"
    )
    assert admin.may_manage_source({"id": "s", "min_rank": 40, "owner_id": "u1"}), "except their own"
    individual = Principal.for_user({"id": "u2", "username": "bob"}, roles["individual"])
    assert not individual.can("manage_users")
    assert not individual.may_manage_source({"id": "s", "min_rank": 0, "owner_id": "x"})
    with pytest.raises(ValueError):
        admin.can("fly")


def test_open_mode_principal_sees_everything_and_can_do_anything() -> None:
    p = Principal.open()
    assert p.is_open and p.access.unrestricted
    assert all(p.can(c) for c in ("manage_users", "manage_roles", "edit_graph"))
    assert p.name == "everyone (open mode)"
    preview = p.as_role({"id": "individual", "name": "Individual", "rank": 0, "capabilities": []})
    assert not preview.access.unrestricted and preview.access.rank == 0


def test_ladder_helpers() -> None:
    assert top_role(DEFAULT_ROLES)["id"] == "arch-admin"
    assert [r["id"] for r in roles_at_or_below(DEFAULT_ROLES, 20)] == [
        "local-admin",
        "local-assistant",
        "individual",
    ]


# ------------------------------------------------------------ roles & users


def test_roles_are_seeded_once_and_edits_survive_a_reseed(store) -> None:
    store.ping()
    roles = store.list_roles()
    assert [r["id"] for r in roles] == [r["id"] for r in DEFAULT_ROLES]
    assert roles[0]["rank"] > roles[-1]["rank"]
    store.update_role("individual", name="Member", rank=1)
    store.ensure_roles()
    assert store.get_role("individual")["name"] == "Member"
    assert store.get_role("individual")["rank"] == 1


def test_role_crud_validation_and_in_use_protection(store) -> None:
    store.ping()
    rid = store.create_role("Site lead", 15, "between assistant and admin", ["add_sources", "run_evals"])
    role = store.get_role(rid)
    assert role["rank"] == 15 and role["capabilities"] == ["add_sources", "run_evals"] and not role["builtin"]
    with pytest.raises(ValueError):
        store.create_role("Bad", 5, capabilities=["fly"])
    with pytest.raises(ValueError):
        store.update_role(rid, rank=-1)
    with pytest.raises(ValueError):
        store.update_role(rid, colour="red")
    uid = store.create_user("lead", "secret1", rid)
    with pytest.raises(ValueError, match="still used"):
        store.delete_role(rid)
    store.update_user(uid, role_id="individual")
    store.delete_role(rid)
    assert store.get_role(rid) is None
    assert store.get_user(uid)["role_id"] == "individual"


def test_moving_a_role_on_the_ladder_moves_its_sources(store) -> None:
    store.ping()
    sid = store.create_source("text", "Notes", access_role_id="local-assistant")
    assert store.get_source(sid)["min_rank"] == 10
    store.update_role("local-assistant", rank=25)
    assert store.get_source(sid)["min_rank"] == 25
    assert store.get_source(sid, Access(rank=20)) is None, "a local admin no longer sees it"
    assert store.get_source(sid, Access(rank=25)) is not None


def test_users_crud_login_and_tokens(store) -> None:
    store.ping()
    assert store.count_users() == 0
    uid = store.create_user("Ann.Lee", "secret1", "regional-admin", display_name="Ann")
    user = store.get_user(uid)
    assert user["username"] == "ann.lee" and user["role_name"] == "Regional admin" and user["rank"] == 30
    assert user["token"].startswith("hippo_")
    assert store.get_user_by_token(user["token"])["id"] == uid
    assert store.check_password("ann.lee", "secret1")["id"] == uid
    assert store.check_password("ANN.LEE", "secret1")["id"] == uid
    assert store.check_password("ann.lee", "wrong") is None
    with pytest.raises(ValueError, match="taken"):
        store.create_user("ann.lee", "secret1", "individual")
    with pytest.raises(ValueError):
        store.create_user("a", "secret1", "individual")
    with pytest.raises(ValueError, match="no such role"):
        store.create_user("bob", "secret1", "ceo")
    new_token = store.rotate_token(uid)
    assert new_token != user["token"] and store.get_user_by_token(user["token"]) is None
    store.update_user(uid, disabled=True)
    assert store.check_password("ann.lee", "secret1") is None
    store.update_user(uid, disabled=False, password="secret2")
    assert store.check_password("ann.lee", "secret2")["id"] == uid
    assert [u["username"] for u in store.list_users()] == ["ann.lee"]
    sid = store.create_source("text", "Ann's notes", owner_id=uid, access_role_id="regional-admin")
    assert store.get_user(uid)["sources"] == 1
    store.delete_user(uid)
    assert store.get_user(uid) is None
    assert store.get_source(sid)["owner_id"] is None, "her sources stay, without an owner"


def test_set_source_access(store) -> None:
    store.ping()
    sid = store.create_source("text", "Notes")
    assert store.get_source(sid)["access_role_name"] == "Everyone"
    store.set_source_access(sid, "arch-admin", owner_id="u9")
    row = store.get_source(sid)
    assert row["access_role_id"] == "arch-admin" and row["min_rank"] == 40 and row["owner_id"] == "u9"
    store.set_source_access(sid, None)
    row = store.get_source(sid)
    assert row["min_rank"] == 0 and row["owner_id"] == "u9", "leaving owner_id out keeps the owner"
    with pytest.raises(ValueError):
        store.set_source_access(sid, "nope")


# ------------------------------------------------------- the Cypher predicate


def test_every_read_hides_restricted_sources_and_what_only_they_support(
    ctx: AppContext, sample_text: str
) -> None:
    open_id, restricted_id = index_split(ctx, sample_text)
    store = ctx.store

    # Sources
    assert {s["id"] for s in store.list_sources()} == {open_id, restricted_id}
    assert {s["id"] for s in store.list_sources(INDIVIDUAL)} == {open_id}
    assert {s["id"] for s in store.list_sources(LOCAL_ADMIN)} == {open_id, restricted_id}
    assert {s["id"] for s in store.list_sources(OWNER)} == {open_id, restricted_id}
    assert store.get_source(restricted_id, INDIVIDUAL) is None
    assert store.get_source(restricted_id, LOCAL_ADMIN)["access_role_name"] == "Local admin"

    # Passages
    hidden = store.passage_ids_for_source(restricted_id)
    shown = store.passage_ids_for_source(open_id)
    assert hidden and shown
    assert store.get_passages(hidden, INDIVIDUAL) == []
    assert len(store.get_passages(hidden + shown, INDIVIDUAL)) == len(shown)
    assert store.passages_for_source(restricted_id, access=INDIVIDUAL) == []
    assert len(store.passages_for_source(restricted_id, access=LOCAL_ADMIN)) == len(hidden)

    # Entities: only those a visible passage mentions, with counts over visible passages only
    all_entities = store.load_entities()
    mentioned_by_open = {r["entity_id"] for r in store.load_mentions() if r["passage_id"] in set(shown)}
    visible = store.get_entities([e["id"] for e in all_entities], INDIVIDUAL)
    assert {e["id"] for e in visible} == mentioned_by_open
    assert visible, "the open half mentions something"
    for e in visible:
        assert e["passage_count"] <= len(shown)
    assert {e["id"] for e in store.get_entities([e["id"] for e in all_entities], LOCAL_ADMIN)} == {
        e["id"] for e in all_entities
    }

    # Facts: only those a visible passage states, listing visible passages only
    all_facts = store.load_facts()
    for row in store.get_facts([f["id"] for f in all_facts], INDIVIDUAL):
        assert row["passage_ids"] and set(row["passage_ids"]) <= set(shown)
    assert len(store.get_facts([f["id"] for f in all_facts], INDIVIDUAL)) < len(all_facts)

    # Name search
    names = [e["name"] for e in all_entities]
    everything = {e["id"] for name in names for e in store.search_entities(name)}
    for_individual = {e["id"] for name in names for e in store.search_entities(name, access=INDIVIDUAL)}
    assert for_individual == mentioned_by_open
    assert for_individual < everything


# ------------------------------------------------------------ scoped graph


def test_scoped_index_is_the_induced_subgraph_of_visible_sources(ctx: AppContext, sample_text: str) -> None:
    open_id, restricted_id = index_split(ctx, sample_text)
    full = GraphIndex.load(ctx.store)
    scoped = full.scoped({open_id})

    assert full.scoped({open_id, restricted_id}) is full, "nothing hidden: the full index is shared"
    assert {p.source_id for p in scoped.passages} == {open_id}
    assert 0 < len(scoped.passages) < len(full.passages)
    visible_pids = {p.id for p in scoped.passages}

    # Entities: exactly those mentioned by a visible passage; counts recomputed over visible passages.
    mentioned = set()
    for (a, b), e in full.edges.items():
        if e.mention:
            ent, pas = (a, b) if full.node_kind[a] == "entity" else (b, a)
            if full.node_ids[pas] in visible_pids:
                mentioned.add(full.node_ids[ent])
    assert set(scoped.node_ids[: scoped.num_entities]) == mentioned
    assert 0 < scoped.num_entities < full.num_entities
    for v in range(scoped.num_entities):
        assert 1 <= scoped.entity_passage_count[v] <= len(scoped.passages)
        eid = scoped.node_ids[v]
        assert scoped.entity_passage_count[v] <= full.entity_passage_count[full.idx_of[eid]]

    # Facts: only those stated by a visible passage, with only visible passages listed.
    assert scoped.facts and len(scoped.facts) < len(full.facts)
    for f in scoped.facts:
        assert f.passage_ids and set(f.passage_ids) <= visible_pids
    assert scoped.fact_embeddings.shape == (len(scoped.facts), full.fact_embeddings.shape[1])
    assert scoped.passage_embeddings.shape == (len(scoped.passages), full.passage_embeddings.shape[1])

    # Edges: only among kept nodes, fact counts from visible statements; igraph agrees with the dict.
    for (a, b), e in scoped.edges.items():
        assert a < scoped.num_nodes and b < scoped.num_nodes
        if e.fact_count:
            assert (
                e.fact_count
                <= full.edge_between(
                    full.idx_of[scoped.node_ids[a]], full.idx_of[scoped.node_ids[b]]
                ).fact_count
            )
    assert scoped.graph.vcount() == scoped.num_nodes
    assert scoped.graph.ecount() == sum(1 for e in scoped.edges.values() if e.weight > 0)
    # Vertex bookkeeping still lines up.
    assert [scoped.node_ids[int(v)] for v in scoped.passage_vertices] == [p.id for p in scoped.passages]
    assert all(scoped.idx_of[nid] == i for i, nid in enumerate(scoped.node_ids))
    assert scoped.version == full.version


# ------------------------------------------------------ scoped code graph


def index_code(ctx: AppContext) -> tuple[str, str, dict[str, str]]:
    """Two code sources, one open and one restricted, each with a symbol defined in its own passage
    and a code edge between them. Returns (open_id, restricted_id, {name: node id})."""
    ctx.store.ping()
    open_id = ctx.store.create_source("repo", "Open repo")
    hidden_id = ctx.store.create_source("repo", "Secret repo", owner_id="boss", access_role_id="local-admin")
    ids = {
        "open_symbol": make_id("symbol-", "open"),
        "hidden_symbol": make_id("symbol-", "hidden"),
        "open_data": make_id("data-", "orders"),
        "hidden_commit": make_id("commit-", "abc"),
    }
    for source_id, passage_id, title in (
        (open_id, "passage-open", "open.py :: run"),
        (hidden_id, "passage-hidden", "secret.py :: leak"),
    ):
        ctx.store.add_passages(
            [
                {
                    "id": passage_id,
                    "source_id": source_id,
                    "ordinal": 0,
                    "title": title,
                    "text": title,
                    "embedding": [1.0, 0.0],
                }
            ]
        )
    ctx.store.add_symbols(
        [
            {"id": ids["open_symbol"], "source_id": open_id, "name": "run", "qualname": "open.run"},
            {"id": ids["hidden_symbol"], "source_id": hidden_id, "name": "leak", "qualname": "secret.leak"},
        ]
    )
    ctx.store.add_data_objects(
        [{"id": ids["open_data"], "source_id": open_id, "name": "orders", "kind": "table"}]
    )
    ctx.store.add_commits(
        [{"id": ids["hidden_commit"], "source_id": hidden_id, "sha": "abc1234", "ordinal": 0}]
    )
    ctx.store.link_definitions(
        [
            (ids["open_symbol"], "passage-open"),
            (ids["open_data"], "passage-open"),
            (ids["hidden_symbol"], "passage-hidden"),
            (ids["hidden_commit"], "passage-hidden"),
        ]
    )
    ctx.store.add_code_edges(
        [
            {"a": ids["open_symbol"], "b": ids["hidden_symbol"], "kind": "INVOKES", "omega": 0.9},
            {"a": ids["open_symbol"], "b": ids["open_data"], "kind": "READS", "omega": 0.85},
        ]
    )
    ctx.store.set_node_boost(ids["open_symbol"], 1.5)
    ctx.store.bump_graph_version()
    return open_id, hidden_id, ids


def test_get_symbols_hides_a_restricted_sources_code(ctx: AppContext) -> None:
    _open_id, _hidden_id, ids = index_code(ctx)
    assert [r["id"] for r in ctx.store.get_symbols(list(ids.values()), INDIVIDUAL)] == [ids["open_symbol"]]
    assert ctx.store.get_commits([ids["hidden_commit"]], INDIVIDUAL) == []
    assert ctx.store.get_data_objects([ids["open_data"]], INDIVIDUAL)[0]["name"] == "orders"
    # The owner and an unrestricted read still see everything.
    assert len(ctx.store.get_symbols(list(ids.values()), OWNER)) == 2
    assert len(ctx.store.get_symbols(list(ids.values()))) == 2


def test_scoped_drops_a_hidden_symbol_and_every_edge_touching_it(ctx: AppContext) -> None:
    open_id, _hidden_id, ids = index_code(ctx)
    full = GraphIndex.load(ctx.store)
    scoped = full.scoped({open_id})

    assert {n.id for n in scoped.code_nodes} == {ids["open_symbol"], ids["open_data"]}
    assert ids["hidden_symbol"] not in scoped.idx_of
    assert ids["hidden_commit"] not in scoped.idx_of
    # The INVOKES to the hidden symbol goes with it, in both directions.
    open_v = scoped.idx_of[ids["open_symbol"]]
    assert {e.kind for e in scoped.out_edges(open_v)} == {"DEFINED_IN", "READS"}
    assert all(e.dst < scoped.num_nodes and e.src < scoped.num_nodes for e in scoped.out_edges(open_v))
    assert scoped.graph.vcount() == scoped.num_nodes


def test_scoped_keeps_omega_and_code_kinds_on_surviving_pairs(ctx: AppContext) -> None:
    open_id, _hidden_id, ids = index_code(ctx)
    scoped = GraphIndex.load(ctx.store).scoped({open_id})
    edge = scoped.edge_between(scoped.idx_of[ids["open_symbol"]], scoped.idx_of[ids["open_data"]])
    # Without the copy a restricted reader silently gets a differently *weighted* graph.
    assert edge.omega == pytest.approx(0.85)
    assert edge.code_kinds == ["reads"]
    assert edge.weight == pytest.approx(0.85)


def test_scoped_recomputes_code_specificity_from_what_survived(ctx: AppContext) -> None:
    open_id, _hidden_id, ids = index_code(ctx)
    full = GraphIndex.load(ctx.store)
    scoped = full.scoped({open_id})
    # The hidden symbol's only in-edge was the open symbol's INVOKES, so it is gone with the vertex;
    # the data object keeps its READS and stays at in_degree 1 + 1.
    assert full.specificity[full.idx_of[ids["hidden_symbol"]]] == 2
    assert scoped.specificity[scoped.idx_of[ids["open_data"]]] == 2
    assert scoped.specificity[scoped.idx_of[ids["open_symbol"]]] == 1


def test_scoped_keeps_a_boost_set_on_a_symbol(ctx: AppContext) -> None:
    open_id, _hidden_id, ids = index_code(ctx)
    scoped = GraphIndex.load(ctx.store).scoped({open_id})
    # A changeset that boosts a symbol must work for a restricted reader too, not only in simulation.
    assert scoped.entity_boost[scoped.idx_of[ids["open_symbol"]]] == 1.5


def test_a_scoped_index_gets_its_own_scale_memo(ctx: AppContext) -> None:
    open_id, _hidden_id, _ids = index_code(ctx)
    full = GraphIndex.load(ctx.store)
    scoped = full.scoped({open_id})
    assert scoped.graph_for_scale(0.5) is not full.graph_for_scale(0.5)
    assert scoped.graph_for_scale(1.0) is scoped.graph


def test_scoping_to_nothing_gives_an_empty_index(ctx: AppContext, sample_text: str) -> None:
    index_split(ctx, sample_text)
    empty = GraphIndex.load(ctx.store).scoped(set())
    assert empty.is_empty() and empty.num_nodes == 0 and not empty.facts


def test_search_never_ranks_or_reads_a_hidden_passage(ctx: AppContext, sample_text: str) -> None:
    open_id, restricted_id = index_split(ctx, sample_text)
    hidden = set(ctx.store.passage_ids_for_source(restricted_id))
    # A question whose facts live in the restricted half (the sample's later sections).
    question = "Who designed the Orion arm?"

    everyone = ask_service.search(ctx, question)
    assert hidden & set(everyone.passage_ids()), "sanity: the unrestricted search does reach the hidden half"

    trace = ask_service.search(ctx, question, access=INDIVIDUAL)
    assert not hidden & set(trace.passage_ids())
    assert not hidden & {pid for c in trace.fact_candidates for pid in c.passage_ids}
    assert all(n.node_id not in hidden for n in trace.top_nodes)

    # The owner and a local admin see it again.
    assert hidden & set(ask_service.search(ctx, question, access=OWNER).passage_ids())
    assert hidden & set(ask_service.search(ctx, question, access=LOCAL_ADMIN).passage_ids())

    # The answer can only be written from visible passages.
    _, answer = ask_service.ask(ctx, question, access=INDIVIDUAL)
    assert not hidden & set(answer.passage_ids)


def test_graph_for_caches_by_visible_set_and_forgets_on_invalidate(ctx: AppContext, sample_text: str) -> None:
    index_split(ctx, sample_text)
    full = ctx.graph()
    assert ctx.graph_for(None) is full
    assert ctx.graph_for(EVERYTHING) is full
    a = ctx.graph_for(INDIVIDUAL)
    assert a is not full and a is ctx.graph_for(Access(rank=0, user_id="another-individual"))
    assert ctx.graph_for(LOCAL_ADMIN) is full, "sees every source, so shares the full graph"
    ctx.invalidate_graph()
    assert ctx.graph_for(INDIVIDUAL) is not a
