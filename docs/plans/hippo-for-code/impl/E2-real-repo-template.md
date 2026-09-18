# E2 — Run hippo on one real repository in a new language and grade the answers (small task)

Read `impl/00-impl-context.md` first. You are an exploration/QA worker: **you edit no source and no
test**; you produce one report. Your language, repo, worktree and port are in the spawn message:

| Language | Repo on disk | Worktree / branch | Server port / data dir | Report |
|---|---|---|---|---|
| Go | `/Users/mascott/projects/mgodatagen` (37 `.go` files, git, a MongoDB data generator) | `.worktrees/e2go`, `wp/e2go` | 8015, `/tmp/hippo-e2go` | `research/E2-go-mgodatagen.md` |
| Rust | `/Users/mascott/projects/headroom` (61 `.rs` files, git) | `.worktrees/e2rs`, `wp/e2rs` | 8016, `/tmp/hippo-e2rs` | `research/E2-rust-headroom.md` |
| C# | `/Users/mascott/projects/vibe-unity` (17 `.cs` files, git) | `.worktrees/e2cs`, `wp/e2cs` | 8017, `/tmp/hippo-e2cs` | `research/E2-csharp-vibe-unity.md` |

Sized to finish inside one worker's first ~300k tokens: index once, ask FIVE questions, grade, write.
Ollama on the host is the real model; never touch port 8000/7687, `data/`, or the live containers.
Follow `research/E1-territory-updater.md` §Methodology for the mechanics (sparse/local checkout as a
repo source through a `clone_repo` monkeypatch launcher, trace capture via `/api/ask`), and read
`research/QA1-real-model-smoke.md` §Methodology for the cost dry-run.

## Do this

1. Dry-run the cost (`readers.read_source` + `extract_code` + `chunk_documents`): documents, chunks,
   OpenIE passages. **Target ≤ 45 minutes of indexing**; if higher, restrict to the main source
   directory (`git sparse-checkout`) and say so. Exclude any data/asset directories and anything that
   looks like personal data. Keep `.git` for history.
2. Start the scratch server BEFORE adding the source (the user may watch `http://127.0.0.1:<port>/`),
   index as a repo source, record `meta["code"]` in full (symbols, `edges_by_kind`, files parsed /
   skipped by reason, `unresolved_calls`, commits, modifies, `history_skipped`, languages), the wall
   time, and the Status pill. **Compare `unresolved_calls_total` to `edges_by_kind["INVOKES"]`** — the
   ratio is the resolver's real-world hit rate for this language; report it.
3. Ask five questions through the Ask page, screenshot each, save the trace: (a) "What does `<a
   central function, display name>` do?"; (b) "Where is `<it>` called?"; (c) a realistic stack trace or
   panic for this language ending in an in-repo frame, pasted with "why would this happen?"; (d)
   "Which commits touched `<it>`?"; (e) one data-access or test-coverage question if the repo has
   either (`Which code writes the <collection>?` for mgodatagen; `What tests cover <X>?` otherwise).
   Grade each against the repo (file:line evidence): correct / partial / wrong / refused. Record seed
   chips (anchored vs dense), the Code graph block, top-5 titles, `timing_ms`.
4. Run `hippo path`, `hippo blast --depth 2`, `hippo history` for the central function against the
   running server (`HIPPO_HOST`/`HIPPO_PORT`); paste outputs.

## Output

The report: a one-paragraph verdict; the five-question table; each question in full; `meta["code"]`
and the cost; **Defects** with reproductions (resolver misses the graph should have made, chips that
should not have fired, chunk titles that look wrong for this language, a crash) and **Surprises**.
Commit the report on your branch. Stop the server, delete the data dir except `shots/`.
`horch tell orchestrator "[<role>] DONE: <report path> — <verdict line>"`, ledger summary, close pane.
