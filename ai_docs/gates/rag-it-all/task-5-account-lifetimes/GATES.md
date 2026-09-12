# Task 5 account and role inventory lifetimes

Scope: source-derived inventory in account/user/role DTOs and pages. Mutation authorization is unchanged; post-mutation presentation acquires its fresh scope after the authorized mutation.

- [x] A1: Account and user/role responses own one snapshot and close it on success, rendering error or revocation.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_account_snapshot_lifetime.py -o addopts='' -q
  EXPECT: 12 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=............                                                             [100%] | 12 passed in 0.78s

- [x] A2: Real Ladybug reference ownership agrees with FakeStore.
  CHECK: HIPPO_TEST_STORE=ladybug .venv/bin/python -m pytest tests/unit/test_account_snapshot_lifetime.py -o addopts='' -q
  EXPECT: 12 passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=............                                                             [100%] | 12 passed in 18.90s

- [x] A3: Existing auth/access/status behavior remains compatible.
  CHECK: HIPPO_TEST_STORE=fake .venv/bin/python -m pytest tests/unit/test_web_auth.py tests/unit/test_access.py tests/unit/test_status_access.py -o addopts='' -q
  EXPECT: passed
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 68 passed, 1 warning in 4.05s

- [x] A4: Owned Python files pass lint and format checks.
  CHECK: .venv/bin/ruff check src/hippo/web/auth.py src/hippo/web/routes/users.py tests/unit/test_account_snapshot_lifetime.py && .venv/bin/ruff format --check src/hippo/web/auth.py src/hippo/web/routes/users.py tests/unit/test_account_snapshot_lifetime.py
  EXPECT: All checks passed!
  EVIDENCE: exit=0; shell=/bin/sh; cwd=/Users/mascott/projects/hippo; path=bf8c82a1dcc8/39 entries; output=All checks passed! | 3 files already formatted

RED: /tmp/hippo-account-lifetime-red.log, 12 ownership failures. Independent adaptive SPEC/QUALITY PASS:56Fake cases and Ruff/format clean. Root isolatedNeo12passed, rootledger4/4MET including12Fake/12Ladybug and68compatibility.
