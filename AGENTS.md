- Use Pydantic v2 models for configuration and domain validation.
- Translate Pydantic, RDF parser, and storage corruption failures into the repository's
  user-facing error types where appropriate.

- Use `uv` and keep `uv.lock` updated:

```console
uv run pytest -W error
uv run ruff check .
uv run ruff format --check .
uv build
```

- Tests should assert behavior, not check backwards compatibility.

- Before finishing, inspect `git status` and avoid staging generated workspaces, databases, build
  artifacts, caches, or unrelated user files.
