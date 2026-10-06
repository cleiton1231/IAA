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
