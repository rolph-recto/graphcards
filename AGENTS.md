**IMPORTANT**: before you do anything else, run the `beans prime` command and heed its output.

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

- The web UI is styled with Tailwind CSS. Edit the templates or
  `src/graphcards/web/style.src.css`, then rebuild the committed stylesheet:

```console
uv run tailwindcss -i src/graphcards/web/style.src.css -o src/graphcards/web/static/style.css --minify
```

- Tests should assert behavior, not check backwards compatibility.

- When completing a bean, commit its bean file together with the implementation changes that
  deliver it. Prefix the commit subject with the bean ID, for example:
  `[graphcards-xxxx] Implement the feature`.

- Before finishing, inspect `git status` and avoid staging generated workspaces, databases, build
  artifacts, caches, or unrelated user files.
