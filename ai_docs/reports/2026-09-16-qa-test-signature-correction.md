# QA test-signature correction

Changed only `tests/unit/test_managed_route_activation.py`. The two monkeypatched
`_answer_from_trace` helpers now declare `*, qa_model=None` and explicitly forward
that value. Existing authorization and embedding-profile assertions are unchanged.

Each test covers inherited QA (`None`) and explicit same-base QA
(`ctx.config.llm_model`). The fixture configuration and client QA model are aligned
before each query, and each wrapper asserts the exact forwarded QA model.

## Results

- Before: 2 focused cases.
- After: 4 focused cases.
- Focused command: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_route_activation.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning' -k 'authorization_change_during_output or embedding_tag_change_during_output'`
- Focused output: `4 passed, 22 deselected in 0.14s`.
- Full-file command: `HIPPO_TEST_STORE=fake .venv/bin/pytest tests/unit/test_managed_route_activation.py -q -o addopts='' -W error -W 'ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning'`
- Full-file output: `26 passed in 2.24s`.
- `.venv/bin/ruff check tests/unit/test_managed_route_activation.py`: `All checks passed!`
- `.venv/bin/ruff format --check tests/unit/test_managed_route_activation.py`: `1 file already formatted`.
- `git diff --check`: no output.
- Test-only source SHA-256: `cdf4b4990bf634c273f7e1ec401c81ed3181f3489931c853c9c01960a12f7a4f`.

No application sources, model/socket/corpus work, full repository suite, or commits
were involved.
