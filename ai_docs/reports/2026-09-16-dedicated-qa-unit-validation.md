# Dedicated QA unit validation

All 5,607 final collected unit cases are accounted for: 5,572 passed and 35 skipped across the full run and focused reruns. This is coverage accounting, not a claim that one final full-suite invocation exited green.

The full fake-store run on frozen application source reported 5,560 passed, 35 skipped, eight failed and two errors (451.46 seconds), at /tmp/hippo-dedicated-qa-final-full-unit.log. Two failures were obsolete monkeypatched private-helper signatures; six failures and two fixture errors were localhost socket bindings denied by the managed sandbox. No application source changed during or after that run, verified against /tmp/hippo-dedicated-qa-final-full-unit-start.json.

The two helper signatures were updated to forward qa_model and parameterized for inherited and explicit QA, preserving their original authorization and rebuild assertions. The complete managed-route module then passed26 cases; see qa-test-signature-correction.md. The complete local HTTP module passed19 cases with permission to bind its temporary localhost sockets; /tmp/hippo-dedicated-qa-http-rerun.log and .xml. Those reruns cover every failed/error node. The two new parameter cases account for the increase from5,605 to5,607 collected cases. /tmp/hippo-dedicated-qa-final-collection.log confirms the final collection.

Commands use HIPPO_TEST_STORE=fake, root .venv, pytest -q -o addopts='', warnings-as-errors and only the previously documented anyio BlockingPortal alias warning filter. No live model/corpus was used. Dedicated gates85/430, focused Ladybug39, public-errors94, static checks, independent review and six-request production-body equality are separately recorded. G3 remains pending real-model evaluation.
