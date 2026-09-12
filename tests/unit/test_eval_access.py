"""Evaluation ownership and current evidence access precede every saved-text read."""

import importlib
from types import SimpleNamespace

import pytest

from hippo.access import Principal
from hippo.hipporag.graph_index import GraphIndex
from hippo.hipporag.retriever import RankedPassage, Trace
from hippo.knowledge.replay import view_fingerprint


def api():
    try:
        return importlib.import_module("hippo.knowledge.eval_access")
    except ModuleNotFoundError:
        pytest.fail("Evaluation ownership service is missing")


def readers(ctx):
    ctx.store.ensure_roles()
    users = [ctx.store.create_user(name, "correct-password", "arch-admin") for name in ("alice", "bob")]
    return [
        Principal.for_user(ctx.store.get_user(user), ctx.store.get_role("arch-admin")).access
        for user in users
    ]


def source(ctx):
    identity = ctx.store.create_source("text", "source")
    ctx.store.add_passages(
        [
            dict(
                id="public-p",
                source_id=identity,
                title="public",
                text="public original",
                ordinal=0,
                embedding=[1.0, 0.0],
            )
        ]
    )
    ctx.store.bump_graph_version()
    return identity


def owned(ctx, access, **kwargs):
    service = api().EvalAccess(ctx, access)
    identity = service.create_question_set("owned name", **kwargs)
    questions = service.add_questions(
        identity, [dict(text="owned question", expected_answer="owned expected")]
    )
    return service, identity, questions[0]


def test_other_user_cannot_list_read_or_mutate_owned_evaluations(ctx):
    module = api()
    alice, bob = readers(ctx)
    service, set_id, question_id = owned(ctx, alice)
    run = ctx.store.create_run(set_id, "private run", ctx.store.get_settings())
    result = ctx.store.add_result(run, question_id, dict(answer="private result"))
    other = module.EvalAccess(ctx, bob)
    assert not other.list_question_sets() and not other.list_runs()
    assert other.get_question_set(set_id) is None and other.get_question(question_id) is None
    assert other.get_run(run) is None and other.get_result(result) is None
    assert not other.results_for_question(question_id)
    for operation in (
        lambda: other.add_questions(set_id, [dict(text="attack")]),
        lambda: other.delete_question(question_id),
        lambda: other.delete_run(run),
        lambda: other.delete_question_set(set_id),
    ):
        with pytest.raises(module.EvalAccessDenied):
            operation()
    assert service.get_question(question_id)["text"] == "owned question"


def test_unowned_legacy_sets_fail_closed_after_users_exist(ctx):
    module = api()
    identity = ctx.store.create_question_set("legacy private")
    assert module.EvalAccess(ctx, Principal.open().access).get_question_set(identity)
    alice, _ = readers(ctx)
    assert module.EvalAccess(ctx, alice).get_question_set(identity) is None
    assert module.EvalAccess(ctx, Principal.open().access).get_question_set(identity) is None


@pytest.mark.parametrize("field", ["audience", "origin"])
def test_malformed_owner_metadata_fails_closed(ctx, field):
    import json

    api()
    alice, _ = readers(ctx)
    service, identity, _ = owned(ctx, alice)
    metadata = json.loads(ctx.store.get_meta("eval_owner:" + identity))
    metadata[field] = []
    ctx.store.set_meta("eval_owner:" + identity, json.dumps(metadata))
    assert service.get_question_set(identity) is None


def test_question_owner_is_checked_before_loading_question_text(ctx, monkeypatch):
    module = api()
    alice, bob = readers(ctx)
    _, _, question = owned(ctx, alice)

    def forbidden(_):
        pytest.fail("Read question text before establishing owner")

    monkeypatch.setattr(ctx.store, "get_question", forbidden)
    assert module.EvalAccess(ctx, bob).get_question(question) is None


def test_source_revocation_blocks_an_owners_source_bound_set(ctx):
    api()
    alice, _ = readers(ctx)
    identity = source(ctx)
    service, set_id, _ = owned(ctx, alice, source_id=identity)
    assert service.get_question_set(set_id)
    ctx.store.update_role("arch-admin", rank=0)
    ctx.store.set_source_access(identity, "local-admin")
    assert service.get_question_set(set_id) is None


def test_deleted_source_does_not_erase_the_sets_access_requirement(ctx):
    api()
    alice, _ = readers(ctx)
    identity = source(ctx)
    service, set_id, _ = owned(ctx, alice, source_id=identity)
    ctx.store.delete_source(identity)
    assert service.get_question_set(set_id) is None


def test_generated_question_text_is_withheld_when_its_input_view_changes(ctx):
    api()
    alice, _ = readers(ctx)
    identity = source(ctx)
    service, set_id, question = owned(ctx, alice, source_id=identity, origin="generated")
    assert service.get_question(question)
    ctx.store.add_passages(
        [
            dict(
                id="new-p",
                source_id=identity,
                title="new",
                text="new content",
                ordinal=1,
                embedding=[0.0, 1.0],
            )
        ]
    )
    ctx.store.bump_graph_version()
    assert service.get_question_set(set_id) is None and service.get_question(question) is None


def test_result_reconstructs_trace_and_withholds_answer_and_metrics_after_view_change(ctx):
    api()
    alice, _ = readers(ctx)
    identity = source(ctx)
    service, set_id, question = owned(ctx, alice)
    run = ctx.store.create_run(set_id, "run", ctx.store.get_settings())
    graph = ctx.graph_for(alice)
    trace = Trace(
        question="untrusted saved question",
        settings={},
        graph_version=graph.version,
        evidence_fingerprint=view_fingerprint(graph),
    )
    trace.passages = [
        RankedPassage(
            "public-p",
            1,
            9,
            1,
            9,
            "SECRET saved title",
            identity,
            "SECRET saved source",
            "SECRET saved preview",
        )
    ]
    result_id = ctx.store.add_result(
        run,
        question,
        dict(
            answer="generated answer",
            thought="private thought",
            judge_score=1,
            judge_reason="private judgment",
            trace=trace.to_dict(),
        ),
    )
    result = service.get_result(result_id)
    assert result["answer"] == "generated answer"
    assert result["trace"]["passages"][0]["preview"] == "public original"
    ctx.store.add_passages(
        [dict(id="new-p", source_id=identity, title="new", text="new", ordinal=1, embedding=[0.0, 1.0])]
    )
    ctx.store.bump_graph_version()
    stale = service.get_result(result_id)
    assert stale["answer"] == stale["thought"] == stale["judge_reason"] == ""
    assert stale["judge_score"] is None and stale["recall"] == {}
    assert stale["trace"]["question"] == "owned question"
    assert service.get_run(run)["summary"] == {}
    assert "SECRET" not in repr(stale)


POISON_ERROR = (
    "EmbeddingProfileMismatch: token=sk-live-DEADBEEF /Users/someone/notes.md "
    "'Acme Robotics is headquartered in Boulder.'"
)


def failed_result(ctx, service, set_id, question, stored_error):
    run = ctx.store.create_run(set_id, "run", ctx.store.get_settings())
    return run, ctx.store.add_result(run, question, dict(answer="", error=stored_error))


def test_a_failed_result_passes_its_closed_code_through_and_nothing_else(ctx):
    """A reader learns *that* retrieval failed and *which* closed family, never the text.

    The runner stores the code it already computed as the first segment of `error`, the way
    `managed_activation.record_build_failure` does. `error` itself stays nulled: the rest of
    the string is `f"{type(exc).__name__}: {exc}"`, and several of the exceptions in the
    public table carry a model reply body or an absolute path by construction.
    """
    api()
    alice, _ = readers(ctx)
    service, set_id, question = owned(ctx, alice)
    _, result_id = failed_result(
        ctx, service, set_id, question, f"retrieval_rebuild_required: {POISON_ERROR}"
    )
    result = service.get_result(result_id)
    assert result["failure_code"] == "retrieval_rebuild_required"
    assert result["error"] is None
    assert "sk-live-DEADBEEF" not in repr(result)
    assert "Acme Robotics" not in repr(result)


def test_a_result_that_did_not_fail_carries_no_code(ctx):
    api()
    alice, _ = readers(ctx)
    service, set_id, question = owned(ctx, alice)
    _, result_id = failed_result(ctx, service, set_id, question, None)
    assert service.get_result(result_id)["failure_code"] is None


@pytest.mark.parametrize(
    "stored,expected",
    [
        ("retrieval_rebuild_required", "retrieval_rebuild_required"),
        ("retrieval_unavailable: OllamaError: boom", "retrieval_unavailable"),
        ("EmbeddingProfileMismatch: boom", "operation_failed"),
        ("sk-live-DEADBEEF: boom", "operation_failed"),
        ("boom", "operation_failed"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
    ids=["code-only", "code-and-text", "class-name", "secret", "no-colon", "empty", "blank", "none"],
)
def test_only_a_real_public_code_is_ever_read_back_out_of_a_stored_error(ctx, stored, expected):
    """Every row written before the closed field existed holds `f"{type(exc).__name__}: {exc}"`.

    Splitting on the first colon and publishing the result would disclose a class name -- or
    worse, whatever a caller once put there -- so the prefix is read back only when it is one
    of the codes `public_failure` itself can return. A row that is nonetheless presenting a
    failure cannot fall silent, so it takes the documented `operation_failed` fallback.
    """
    api()
    alice, _ = readers(ctx)
    service, set_id, question = owned(ctx, alice)
    _, result_id = failed_result(ctx, service, set_id, question, stored)
    result = service.get_result(result_id)
    assert result["failure_code"] == expected
    assert result["error"] is None
    assert "sk-live-DEADBEEF" not in repr(result)
    assert "EmbeddingProfileMismatch" not in repr(result["failure_code"])


def test_a_run_of_routing_failures_still_reports_its_summary(ctx):
    """Nothing was saved, so nothing is withheld, so the error count survives the read.

    `get_run` blanks the summary when any result withholds its answer. A question that
    failed before it retrieved stored no trace, which used to read as "withheld" and took
    the whole summary -- the error count included -- with it.
    """
    api()
    alice, _ = readers(ctx)
    service, set_id, question = owned(ctx, alice)
    run, result_id = failed_result(
        ctx, service, set_id, question, f"retrieval_rebuild_required: {POISON_ERROR}"
    )
    assert service.get_result(result_id)["answer_withheld"] is False
    stored_run = service.get_run(run)
    assert stored_run["summary"]["errors"] == 1
    assert stored_run["summary"]["error_codes"] == ["retrieval_rebuild_required"]
    assert "sk-live-DEADBEEF" not in repr(stored_run)


def test_a_failed_question_set_and_run_pass_their_closed_code_through(ctx):
    api()
    alice, _ = readers(ctx)
    service, set_id, question = owned(ctx, alice)
    run, _ = failed_result(ctx, service, set_id, question, None)
    ctx.store.update_question_set(set_id, status="failed", error=f"retrieval_unavailable: {POISON_ERROR}")
    ctx.store.update_run(run, status="failed", error=f"operation_failed: {POISON_ERROR}")
    question_set = service.get_question_set(set_id)
    assert question_set["failure_code"] == "retrieval_unavailable"
    assert question_set["error"] is None
    stored_run = service.get_run(run)
    assert stored_run["failure_code"] == "operation_failed"
    assert stored_run["error"] is None
    assert "sk-live-DEADBEEF" not in repr((question_set, stored_run))


def test_new_set_and_ownership_roll_back_together(ctx, monkeypatch):
    module = api()
    alice, _ = readers(ctx)
    original = ctx.store.set_meta

    def failing(key, value):
        if key.startswith("eval_owner:"):
            raise RuntimeError("injected ownership failure")
        return original(key, value)

    monkeypatch.setattr(ctx.store, "set_meta", failing)
    with pytest.raises(RuntimeError, match="ownership failure"):
        module.EvalAccess(ctx, alice).create_question_set("must roll back")
    assert not ctx.store.list_question_sets()


def test_owner_metadata_survives_ladybug_reopen(tmp_path):
    module = api()
    from hippo.store.ladybug import LadybugStore

    path = tmp_path / "eval-ownership.lbug"
    store = LadybugStore(path)

    def context(current):
        return SimpleNamespace(
            store=current,
            ollama=SimpleNamespace(),
            graph_for=lambda access, **kwargs: GraphIndex.load(current).scoped(
                {row["id"] for row in current.list_sources(access)}
            ),
        )

    ctx = context(store)
    alice, bob = readers(ctx)
    _, identity, question = owned(ctx, alice)
    store.close()
    reopened = LadybugStore(path)
    try:
        assert module.EvalAccess(context(reopened), alice).get_question(question)["text"] == "owned question"
        assert module.EvalAccess(context(reopened), bob).get_question_set(identity) is None
    finally:
        reopened.close()


@pytest.mark.filterwarnings("ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning")
def test_http_eval_reads_and_mutations_enforce_the_same_owner(ctx):
    from fastapi.testclient import TestClient

    from hippo.web.app import create_app

    api()
    alice, bob = readers(ctx)

    def headers(access):
        return {"Authorization": "Bearer " + ctx.store.get_user(access.user_id)["token"]}

    with TestClient(create_app(ctx), base_url="http://localhost") as client:
        created = client.post(
            "/api/evals/sets",
            headers=headers(alice),
            json={
                "name": "alice private set",
                "questions": [
                    {"text": "alice private question", "expected_answer": "alice private expected"}
                ],
            },
        ).json()
        identity = created["set_id"]
        assert client.get("/api/evals/sets", headers=headers(bob)).json() == []
        assert client.get("/api/evals/sets/" + identity, headers=headers(bob)).status_code == 404
        assert client.delete("/api/evals/sets/" + identity, headers=headers(bob)).status_code == 404
        own = client.get("/api/evals/sets/" + identity, headers=headers(alice))
        assert own.status_code == 200 and own.json()["questions"][0]["text"] == "alice private question"


def test_background_run_authorizes_set_before_starting_work(ctx, monkeypatch):
    from hippo.evals.runner import start_run

    module = api()
    alice, bob = readers(ctx)
    _, identity, _ = owned(ctx, alice)
    started = []
    monkeypatch.setattr(ctx.jobs, "start", lambda *args: started.append(args))
    with pytest.raises(module.EvalAccessDenied):
        start_run(ctx, identity, access=bob)
    assert not started


def test_generated_set_records_its_callers_owner_and_input_fingerprint(ctx):
    from hippo.evals.question_maker import generate_questions

    module = api()
    alice, bob = readers(ctx)
    identity = source(ctx)
    set_id = generate_questions(
        ctx, identity, max_single=0, max_multihop=0, max_code=0, max_commits=0, access=alice
    )
    assert module.EvalAccess(ctx, alice).get_question_set(set_id)
    assert module.EvalAccess(ctx, bob).get_question_set(set_id) is None


def test_generation_rechecks_owner_after_each_model_call(ctx, monkeypatch):
    from hippo.evals.question_maker import generate_questions
    from hippo.knowledge.access import AuthorizationChanged

    module = api()
    alice, _ = readers(ctx)
    identity = source(ctx)

    def revoked(*args, **kwargs):
        ctx.store.update_user(alice.user_id, disabled=True)
        return {"questions": [{"question": "derived secret", "answer": "secret"}]}

    monkeypatch.setattr(ctx.ollama, "chat_json", revoked)
    with pytest.raises((module.EvalAccessDenied, AuthorizationChanged)):
        generate_questions(
            ctx, identity, max_single=1, max_multihop=0, max_code=0, max_commits=0, access=alice
        )


@pytest.mark.parametrize("change", ["epoch", "expiry"])
def test_collection_rechecks_earlier_rows_before_releasing_the_complete_list(ctx, monkeypatch, change):
    from hippo.knowledge.access import AuthorizationChanged

    api()
    alice, _ = readers(ctx)
    service, _, _ = owned(ctx, alice)
    graph = ctx.graph_for(alice)
    expired = [False]

    def validate():
        if expired[0]:
            raise AuthorizationChanged("expired during collection")

    graph.authorization_check = validate
    monkeypatch.setattr(ctx, "graph_for", lambda access, **kwargs: graph)
    original = service.get_question_set

    def revoked_after_first(identity):
        row = original(identity)
        if change == "epoch":
            ctx.store.update_user(alice.user_id, disabled=True)
        else:
            expired[0] = True
        return row

    monkeypatch.setattr(service, "get_question_set", revoked_after_first)
    with pytest.raises(AuthorizationChanged):
        service.list_question_sets()


@pytest.mark.parametrize("change", ["answer_view", "judge_revocation"])
def test_runner_never_releases_partial_output_after_its_input_proof_changes(ctx, monkeypatch, change):
    from hippo.evals import runner

    api()
    alice, _ = readers(ctx)
    source(ctx)
    service, _, question_id = owned(ctx, alice)
    with service.read_scope():
        graph = service.graph()
        trace = Trace(
            question="owned question",
            settings={},
            graph_version=graph.version,
            evidence_fingerprint=view_fingerprint(graph),
        )
    monkeypatch.setattr(runner, "search", lambda *args, **kwargs: trace)

    def answer(*args, **kwargs):
        if change == "answer_view":
            # A new published graph is allowed while this query keeps its old
            # view. Mutating the actual held input must still invalidate it.
            kwargs["session"].graph.passages[0].text = "changed held evidence"
        return SimpleNamespace(answer="generated secret", thought="private thought")

    def judge(*args, **kwargs):
        if change == "judge_revocation":
            ctx.store.update_user(alice.user_id, disabled=True)
        return {"verdict": "correct", "score": 1, "reason": "private judgment"}

    monkeypatch.setattr(runner, "answer_from_trace", answer)
    monkeypatch.setattr(ctx.ollama, "chat_json", judge)
    result = runner.run_question(ctx, service.get_question(question_id), {}, alice)
    assert result["answer"] == result["thought"] == result["judge_reason"] == ""
    assert result["trace"] == {} and result["judge_score"] is None and result["recall"] == {}
    assert result["error"]


def test_generated_names_and_source_labels_come_from_visible_evidence(ctx, monkeypatch):
    from hippo.evals.question_maker import _create_set

    module = api()
    alice, _ = readers(ctx)
    source_id = source(ctx)
    ctx.store.update_source(source_id, name="SECRET source container", status="failed")
    graph = ctx.graph_for(alice)
    graph.authorization_check = None  # fixed projected inventory for this source-label unit test
    original = ctx.store._knowledge_rows
    monkeypatch.setattr(ctx, "graph_for", lambda access, **kwargs: graph)
    monkeypatch.setattr(
        ctx.store,
        "_knowledge_rows",
        lambda kind: [SimpleNamespace(source_id=source_id)] if kind == "Artifact" else original(kind),
    )
    set_id = _create_set(ctx, source_id, None, alice)
    service = module.EvalAccess(ctx, alice)
    row = service.get_question_set(set_id)
    assert row["name"] == "Sample questions: public"
    assert row["source_name"] == "public"
    assert service.get_source(source_id)["status"] == "ready"
    assert "SECRET" not in repr(row)


@pytest.mark.parametrize("target", ["manual", "other_owner", "other_source"])
def test_generation_rejects_an_unverified_target_without_mutating_it(ctx, monkeypatch, target):
    from hippo.evals.question_maker import generate_questions

    module = api()
    alice, bob = readers(ctx)
    source_id = source(ctx)
    _, set_id, _ = owned(
        ctx, alice, source_id=source_id, origin="manual" if target == "manual" else "generated"
    )
    called = []
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *args, **kwargs: called.append(args) or {})
    with pytest.raises(module.EvalAccessDenied):
        generate_questions(
            ctx,
            "other-source" if target == "other_source" else source_id,
            set_id=set_id,
            max_single=1,
            access=bob if target == "other_owner" else alice,
        )
    assert not called
    assert ctx.store.get_question_set(set_id)["status"] == "ready"


def test_comparison_revalidates_the_view_used_by_earlier_questions(ctx, monkeypatch):
    from hippo.evals import runner
    from hippo.knowledge.access import AuthorizationChanged

    api()
    alice, _ = readers(ctx)
    source_id = source(ctx)
    _, set_id, _ = owned(ctx, alice)
    called = []

    def run(*args):
        if not called:
            ctx.store.set_source_access(source_id, "local-admin")
        called.append(True)
        return runner._empty_result() | {"judge_score": 1}

    monkeypatch.setattr(runner, "run_question", run)
    with pytest.raises(AuthorizationChanged):
        runner.compare_with_baseline(ctx, set_id, access=alice)


@pytest.mark.parametrize("boundary", ["search", "answer_from_trace"])
@pytest.mark.parametrize("change", ["source_revoked", "question_deleted"])
@pytest.mark.parametrize("entry", ["service", "model_preparation"])
def test_runner_stops_model_dispatch_if_saved_question_access_changes_at_service_entry(
    ctx, monkeypatch, boundary, change, entry
):
    from hippo.evals import runner

    alice, _ = readers(ctx)
    ctx.store.update_role("arch-admin", rank=0)
    source(ctx)  # Unrelated public evidence remains available after the bound source is revoked.
    bound_source = ctx.store.create_source("text", "question source")
    service, _, question_id = owned(ctx, alice, source_id=bound_source)
    question = service.get_question(question_id)
    calls = []
    monkeypatch.setattr(ctx.ollama, "embed_one", lambda *args, **kwargs: calls.append("embed") or [1.0, 0.0])
    monkeypatch.setattr(ctx.ollama, "chat_json", lambda *args, **kwargs: calls.append("json") or {})
    monkeypatch.setattr(ctx.ollama, "chat_text", lambda *args, **kwargs: calls.append("text") or "answer")
    target = runner if entry == "service" else importlib.import_module("hippo.ask")
    function = boundary if entry == "service" else "_" + boundary
    original = getattr(target, function)

    def change_at_entry(*args, **kwargs):
        if change == "source_revoked":
            ctx.store.set_source_access(bound_source, "local-admin")
        else:
            service.delete_question(question_id)
        calls.clear()
        return original(*args, **kwargs)

    monkeypatch.setattr(target, function, change_at_entry)
    result = runner.run_question(ctx, question, {}, alice)
    assert calls == [], "Saved question text reached a model after its authorization changed"
    assert result["error"] and result["trace"] == {} and result["answer"] == ""
