# GUI development workflow validation

Validated on 2026-10-06 from the `/workspace/IAA` checkout based at
`f849b51d5d83bb9a45cac609991159cadcbadb0d`. Test and browser databases in this
report are synthetic fixtures; these results do not measure a model or GPU.

## Checks

- `/workspace/.venvs/IAA/bin/pytest` — **228 passed**, no skips or failures.
- `/workspace/.venvs/IAA/bin/python -m pytest` — **228 passed**, no skips or failures.
- `/workspace/.venvs/IAA/bin/ruff check src tests` — all checks passed.
- `PIP_CACHE_DIR=/workspace/.cache/pip /workspace/.venvs/IAA/bin/python -m pip check` — no broken requirements. The workspace cache is writable and was selected because the default home cache is read-only in this environment.
- `git diff --check` — passed.

At the base, the standalone `pytest --collect-only -q` entry point failed to
import `tests.gui_helpers` in the three GUI test modules, while `python -m pytest`
collected them. The console entry point did not include the checkout root in its
import path. `pytest.ini` now includes the root, and `tests/__init__.py` gives the
local test package an explicit identity. Both entry points now execute the same
228 tests. No test was skipped or hidden.

The resume/version regressions cover exact version-map equality (including an
extra persisted key), automatic and explicit-ID configuration mismatches, a
genuinely old schema with absent configuration columns, capped manual plus
imported cases persisted as `code: 6` and `imported/code: 1`, and `_apply_cap`
preserving a prefilled version identity. No model or external network calls are
used by these tests.

## Installed wheel and browser

Built a fresh wheel with the available system setuptools backend, without
installing build dependencies:

- Wheel: `/tmp/iaa-gui-task4.8LBKYg/wheelhouse-final/bancada-0.1.0-py3-none-any.whl`
- SHA-256: `afaf3803f8132c061b037e71374d211214556bcb86695e93159d807858a17ece`
- The wheel contains five templates and two static files. Its 30 `bancada/`
  package files are byte-identical to the earlier wheel used for the HTTP and
  Chromium run; the later rebuild included documentation metadata updates only.
- Installed with `--force-reinstall --no-deps` into the existing
  `/workspace/.onboarding/wheel-env`; import from `/tmp` resolved to
  `/workspace/.onboarding/wheel-env/lib/python3.12/site-packages/bancada`, outside
  the checkout. Templates and both static resources resolved from that installed
  package.

The installed GUI was started on `127.0.0.1:8878` against
`/workspace/.onboarding/gui-smoke.sqlite`, a synthetic database with 28 fixture
runs. History, page 2, a model filter, run detail, comparison, CSS, and JavaScript
all returned HTTP 200. Chromium reported zero page errors. At a 390-pixel viewport,
the document width remained 390 pixels. The SQLite file SHA-256 stayed
`d9ff02126060575dd70b099ad3255884869df391d6217a62e400b6891092a170`; the
`sqlite_master` schema snapshot also matched before and after. The server process
started for this check was sent SIGTERM, and port 8878 no longer accepts a
connection.

Screenshots were visually inspected:

- History: `/workspace/.onboarding/gui-final-history.png`
- Detail: `/workspace/.onboarding/gui-final-detail.png`
- Comparison: `/workspace/.onboarding/gui-final-compare.png`
- Mobile history: `/workspace/.onboarding/gui-final-mobile.png`

## Limits

The GUI, wheel, HTTP requests, and screenshots use synthetic records. No local
model was started and no real benchmark was run. The screenshot check covers the
history, detail, comparison, and mobile history views. A separate security audit
has not been run as part of this validation report.

## Scoped functional integration fix — 2026-10-06

Based on the final functional review at `09e2e6e7ab6a7c72bf91f725f03afa7bfb3cbc78`:

- Historical imported-case detection now recognizes the repository's
  `source="imported.humaneval"` form while retaining legacy `source="imported"`
  and `suite="humaneval"` recognition. A loader-contract regression persists
  two runs with the same historical `{"code": 1}` map, reads them through the
  GUI reader, and confirms comparison warns that the version is ambiguous. A
  matching `imported/code` identity does not produce that warning.
- Detail HTML labels persisted check turns 1 and 2. Compact packet checks carry
  the same turn labels; checks without turn metadata keep their previous text.
  The persisted initial failure still makes the case fail.
- `/workspace/.venvs/IAA/bin/pytest` — 230 passed; ruff, cached `pip check`, and
  `git diff --check` passed.
- Fresh wheel built with system setuptools 84.0.0 at
  `/tmp/iaa-functional-fix.2rKxeH/wheelhouse/bancada-0.1.0-py3-none-any.whl`
  (SHA-256 `80932597eeb09af8b862b9faa3f0eb601ea75e52520f0b8fea6277ea8fa55f2a`)
  and installed into `/workspace/.onboarding/wheel-env`. From `/tmp`, the
  installed package resolved to
  `/workspace/.onboarding/wheel-env/lib/python3.12/site-packages/bancada`.
  Targeted WSGI requests returned 200 for historical comparison and run detail;
  rendered turn labels, ambiguity warning, legacy formatting, and aggregate
  failure were asserted. No unchanged full browser run was repeated.

All records used for this validation are synthetic. No model, inference call,
network request, prompt, cap, or dependency was added. This scoped fix does not
include the separate security audit.

## Post-functional security fixes — 2026-10-06

The subsequent audit and scoped Sol approval are recorded in
[security-audit.md](security-audit.md). Runtime fixes at `4fd4c27` add an early
loopback Host gate and handle deeply nested saved JSON as invalid entries.
Independent final verification: 253 tests passed, Ruff/pip check/diff check clean.
A fresh installed wheel exercised six normal HTTP paths, six hostile Host paths,
and all three saved JSON targets, preserving synthetic DB bytes and reaping its
owned server. These are local fixture results, not an inference benchmark.
