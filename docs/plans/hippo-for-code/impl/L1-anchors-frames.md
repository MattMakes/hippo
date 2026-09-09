# L1 — Go, .NET and Rust stack-frame shapes in `hipporag/anchors.py`

Read `impl/00-impl-context.md` first (rules, worktree + venv, test matrix, exit-code capture).
Worktree `.worktrees/l1`, branch `wp/l1`, from the CURRENT tip of `code-graph`. Neo4j test container:
name `hippo-neo4j-l1`, port **17702**.

Your spec is the three **Anchors** paragraphs of `ai_docs/add_langs.md` (Steps 1, 2, 3) and the
`test_anchors.py` bullet under "Tests, per step". This is independent of the language walkers being
built in parallel: `find_anchors` resolves a frame by path (basename `path_index`, suffix match either
way round) and line, and does not care what language the symbol came from. You touch only
`src/hippo/hipporag/anchors.py` and `tests/unit/test_anchors.py` (plus `tests/fakes/code_fixture.py`
if you need a helper that writes symbols with `.go`/`.cs`/`.rs` paths through the store — add, never
change, what is there: `test_ask.py` pins the block built from it).

## Scope

1. **Go panic traces**: two lines per frame — `^\s*(?P<fn>[\w./()*]+)\(.*\)$` then
   `^\s+(?P<path>\S+\.go):(?P<line>\d+)(?: \+0x[0-9a-f]+)?$`; innermost first; `0.8 ** k`; the
   `panic: …` header yields NO exception anchor (Go has no RAISES). `goroutine 1 [running]:` lines are
   ignored. Read a real `go` panic output to get the shapes right (`runtime` frames included — those
   resolve to nothing and must not anchor).
2. **.NET traces**: `^\s*at (?P<fn>[\w.<>`,\[\]]+)\((?:[^)]*)\)(?: in (?P<path>[^:]+\.cs):line
   (?P<line>\d+))?$`; frames without ` in file:line N` resolve by the qualified method name only (last
   two dotted segments against `name_index`, path-qualified so it is never split); the header
   `Unhandled exception. System.X: msg` or `X: msg` yields an exception anchor at 0.8 the way the
   Python `SomeError:` line does.
3. **Rust panics**: `thread '(?P<thread>[^']+)' panicked at (?P<path>\S+\.rs):(?P<line>\d+):\d+` is frame 0;
   `RUST_BACKTRACE=1` frames are `^\s*\d+: (?P<fn>\S+)$` followed by `^\s+at (?P<path>\S+\.rs):(?P<line>\d+)(?::\d+)?$`;
   `std::`/`core::` frames resolve to nothing.
4. `split_question` must route all three trace shapes to the `code` half (the Python/Node patterns
   already do), so the embedding sees the prose sentence only — extend the existing S2.12 test with one
   trace of each shape.
5. **Tests**: one trace of each shape pasted with a sentence, over a store-built index whose symbols
   live at `goapp/orders/service.go`, `csapp/Orders/OrderService.cs`, `rsapp/src/orders.rs` with
   realistic line ranges; assert the innermost frame seeds at 1.0 and the next at 0.8, that runtime /
   framework frames seed nothing, that a frame with an absolute path still finds the repo-relative
   symbol (the existing basename rule), the .NET exception anchor, and that the spike-1 prose corpus
   still yields `[]`. Keep every existing anchors test green unchanged.

## Done when

Three stores + lint green, no pinned assertion changed. Ledger summary lists the three regex names and
the frame kinds (`how` values) you emit so L4 can document them.
`horch tell orchestrator "[<role>] DONE: wp/l1 ..."`, close pane.
