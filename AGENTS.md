**IMPORTANT**: before you do anything else, run the `beans prime` command and heed its output.

- This is a new application built from scratch. That means you should not treat it as a legacy application.
Do not make backwards compatibility tests; do not plan to preserve the internal shape of the codebase.

- Do NOT make any commits without explicit confimation.

- When you are about to create a commit that has implemented a bean, make sure
  that the bean's completion is in the commit's changes.

- Prefix the commit subject with the bean ID, for example:
  `[graphcards-xxxx] Implement the feature`.

- Before finishing, inspect `git status` and avoid staging generated workspaces, databases, build
  artifacts, caches, or unrelated user files.

- Any plan you write should adhere to the ASD-STE100 writing system.

- Run tests and linters before committing:

```console
uv run pytest -W error
uv run ruff check .
uv run ruff format --check .
uv build
```
