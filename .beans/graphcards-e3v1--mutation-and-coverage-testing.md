---
# graphcards-e3v1
title: Mutation and coverage testing
status: todo
type: task
priority: normal
created_at: 2026-07-24T20:10:59Z
updated_at: 2026-07-24T20:12:29Z
---

Add mutation testing and coverage measurement for GraphCards.

Coverage:
- Add pytest-cov or equivalent coverage tooling to the development dependencies and keep uv.lock updated.
- Measure statement and branch coverage for src/graphcards, excluding generated artifacts, templates/static assets where line coverage is not meaningful.
- Establish a documented baseline and enforce a project coverage threshold in local quality checks and CI; ratchet the threshold upward rather than lowering it.
- Publish concise terminal coverage output and machine-readable or CI-consumable reports.

Mutation testing:
- Evaluate and add a maintained Python mutation-testing tool compatible with the supported Python version.
- Run mutations against high-value domain, storage, query-validation, and web-session code; avoid wasting runtime on generated/static files.
- Configure mutation runs with the normal test suite, sensible timeouts, and reproducible settings.
- Triage surviving mutants: strengthen tests for behaviorally important survivors, document intentional equivalent mutants, and exclude only justified cases.
- Track a mutation score baseline and enforce or ratchet a minimum score once runtime is acceptable.

CI and documentation:
- Add explicit commands for coverage and mutation runs to contributor documentation and the project quality workflow.
- Keep the standard fast test/lint/format/build checks separate from the slower mutation job.
- Upload or expose reports when CI supports artifacts, while keeping local commands straightforward.
- Add focused tests where coverage or surviving mutants reveal missing behavioral guarantees; do not add tests solely to execute lines.


Possible libraries and selection guidance:

- `pytest-cov` is the natural coverage integration for this pytest suite. It exposes coverage.py features through pytest, including branch coverage and per-test contexts; configure `--cov=src/graphcards --cov-branch` plus terminal/XML/HTML reports. Official docs: https://pytest-cov.readthedocs.io/en/stable/.
- `coverage.py` is the underlying coverage engine and remains a direct fallback when a standalone `coverage run/report/html/xml` workflow is preferable. The project can use pytest-cov without depending on a second coverage runner.
- `mutmut` is the preferred first mutation-testing candidate because it integrates with pytest, supports pyproject.toml configuration, incremental cached runs, parallel execution, targeted source/function selection, and optional mutation of only covered lines. Its current execution model requires fork support, so verify behavior on the supported macOS/Linux environments. Official docs: https://mutmut.readthedocs.io/en/latest/.
- `Cosmic Ray` is the main alternative to evaluate if mutmut is incompatible or too noisy. It supports explicit mutation sessions and distributed/concurrent execution, but has a more involved configuration and workflow. Official docs: https://cosmic-ray.readthedocs.io/en/latest/.

Initial recommendation: adopt pytest-cov with coverage.py for coverage, trial mutmut against the domain/storage/web-session modules, and retain Cosmic Ray as a fallback after a small compatibility benchmark. Compare Python-version support, pytest integration, runtime, source-selection controls, result persistence, CI behavior, and report usability before locking the tool choice.
