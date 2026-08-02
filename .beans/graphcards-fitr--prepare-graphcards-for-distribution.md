---
# graphcards-fitr
title: Prepare GraphCards for distribution
status: completed
type: task
priority: high
tags:
    - packaging
    - documentation
    - distribution
created_at: 2026-08-02T22:18:39Z
updated_at: 2026-08-02T23:18:22Z
---

# Prepare GraphCards for distribution

## Goal

Make GraphCards installable from built Python artifacts. Give users and contributors clear documentation. Keep the package focused on the current Python and Flask application.

## Packaging scope

- Define complete project metadata in `pyproject.toml`, including the description, Python version, classifiers, project links, and license metadata.
- Choose and add the project license before the first public release. Do not invent license text in implementation.
- Use one source of truth for the package version. Expose the version through `importlib.metadata` or the package API without keeping two values that can drift.
- Keep the `graphcards` console script working after installation.
- Keep the built-in deck template source tree at repository root in `templates/`. Package it as read-only `graphcards/templates` resources, together with all Python modules, README files, and template assets such as the image-occlusion example image. Do not package a user `config.toml` as a template.
- Keep development tools out of runtime dependencies. Keep `uv.lock` current.
- Build both artifacts with `uv build`.
- Install the wheel in a clean environment, run the separate user-wide setup path in an isolated user directory, and run the CLI from the installed package.
- Verify that the user-wide setup path, `graphcards init --template`, `graphcards templates`, `validate`, `sync`, and `status` work without the repository source tree. `init` must create only a deck.
- Add artifact checks for package contents, version metadata, the console script, and packaged resources.

## Documentation structure

Use Markdown files under this Diátaxis layout:

```text
docs/
  index.md
  tutorials/
    getting-started.md
    add-entities-and-generators.md
  how-to/
    create-exercise-type.md
  reference/
    api.md
```

### Tutorials

- `getting-started.md` teaches a new user to install GraphCards, set up the user-wide configuration and template library, create one deck in a chosen directory, add that deck to the configured deck list, validate it, synchronize study state, and start the web interface.
- `add-entities-and-generators.md` teaches a user to edit entities and exercise generators in JSON, TOML, or YAML, validate references, and inspect the generated cards.

### How-to guide

- `create-exercise-type.md` teaches a contributor to add a generator and exercise model, register the type, validate references, generate semantic data, render front and back views, export the public symbols, add examples, and write behavior tests.

### API reference

- `api.md` lists the supported public Python API and its import paths.
- Cover `graphcards.decks`, the deck and entity models, `ExerciseGenerator`, generator context, public exercise types, references, configuration entry points, error types, and package version metadata.
- Mark internal modules and implementation helpers as unsupported. Keep signatures and examples aligned with the code.

## Implementation plan

- [x] Define release metadata, the project license, public project links, and the single package-version source.
- [x] Move `src/graphcards/templates/` to the repository-root `templates/` directory. Update source-checkout lookup, affected tests, and source-distribution inclusion. Keep installed-package resource lookup as the fallback.
- [x] Remove every `config.toml` file from the template tree. Add a strict `AppConfig.templates_paths` field as a non-empty ordered list of paths. Use `~/.graphcards/config.toml` as the default user-wide configuration path and `~/.graphcards/templates/` as the default user-wide template directory. Keep both outside the Python environment. Configure Hatchling to package the source tree as read-only `graphcards/templates` resources. Add a separate user-wide setup path that creates the configuration and template library from packaged resources. Make `graphcards init` read that configuration and copy only one selected deck format, plus required deck assets, into the target directory. It must not create or modify `config.toml`, copy a `templates/` directory, or update the configured deck list. Resolve every `templates_paths` entry relative to the user-wide configuration file, preserve list order, and use the first matching template directory when names overlap. Update source and installed resource lookup.
- [x] Add a clean-artifact test that builds or inspects the wheel and source distribution, installs the wheel in isolation, checks the console script, runs the user-wide setup path in temporary user directories, and runs `graphcards init` to create only a deck.
- [x] Add a resource test that proves `importlib.resources` can discover every bundled template, that setup can populate the user-wide template library, and that `init` copies only the selected deck and required assets.
- [x] Create the `docs/` Diátaxis tree and write the two tutorials, the exercise-type how-to guide, the API reference, and the documentation index.
- [x] Update the README to act as a short project landing page and link to the four document types. Remove instructions that do not match the packaged command flow.
- [x] Add or improve public docstrings and `__all__` declarations needed by the API reference. Do not document private implementation details as stable API.
- [x] Add documentation examples for JSON, TOML, and YAML decks and for the current exercise generator types.
- [x] Test the documented command paths with temporary user configuration/data directories and temporary deck directories. Keep tests focused on behavior and package artifacts.
- [x] Run `uv run pytest -W error`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv build`.

## Acceptance checks

- [x] `uv build` creates a wheel and a source distribution with the expected project metadata.
- [x] A clean environment can install the wheel and run `graphcards --help`.
- [x] The user-wide setup path creates `~/.graphcards/config.toml` and `~/.graphcards/templates/` outside `site-packages`. The configuration declares a non-empty `templates_paths` list, and an installed package can list the unique configured templates and initialize each one without access to the repository source tree. `init` creates only the selected deck and its required assets.
- [x] The installed package includes the image-occlusion asset and every file needed by `graphcards init`.
- [x] The package version is available from one source and matches the distribution metadata.
- [x] `docs/` follows the requested Diátaxis structure.
- [x] The getting-started tutorial sets up user-wide files, creates one deck without changing those files, registers the deck, and reaches a working study session.
- [x] The deck-authoring tutorial covers entities, references, generator configuration, validation, and all three supported deck formats.
- [x] The exercise-type how-to guide covers the complete extension path and points to behavior tests.
- [x] The API reference names supported import paths, models, methods, and errors without promising private interfaces.
- [x] README links and all documented commands remain valid.
- [x] All required validation commands pass.

## Out of scope

- Publishing to PyPI or another index.
- Release signing, CI release jobs, and credential management.
- A hosted documentation website or a documentation theme.
- Changes to the deck model, exercise behavior, or SQLite migration work.


## User-wide installation layout

Keep one template source tree at repository root: `templates/`. During a source checkout, `scaffold.py` reads that tree. During installation, Hatchling maps it to read-only `graphcards/templates` resources, and `scaffold.py` reads those resources through `importlib.resources`.

Use `~/.graphcards/` for user-owned GraphCards files by default:

```text
~/.graphcards/
  config.toml
  templates/

<deck directory>/
  deck.json
```

`~/.graphcards/config.toml` is the default configuration path. The `--config` option may override it for tests or another user profile. The package installation must not create or modify `~/.graphcards/`. A separate user-wide setup path must create `config.toml` and `templates/`, then populate `templates/` from the packaged resources. Keep the exact setup command documented and tested.

`graphcards init --template NAME` reads `~/.graphcards/config.toml` by default. It copies only one selected deck format and the assets that the deck requires into the target directory. It does not create `config.toml`, copy `templates/`, copy a template README, or update the user-wide deck list. Document the separate step that adds the new deck to the configured deck list.


## User-wide template configuration

`config.toml` is a user-wide configuration file. It is not a deck template and it is not a per-deck workspace file. The default path is `~/.graphcards/config.toml`. It must declare a non-empty ordered list of user-wide template directories:

```toml
templates_paths = ["templates"]
```

Resolve each relative `templates_paths` entry from the directory that contains the user-wide `config.toml`. Preserve the declared order. When two directories contain the same template name, the first directory wins. Treat the list as authoritative. Do not infer any entry from the current working directory, the Python environment, or `src/graphcards`. Support an explicit configuration path for tests and alternate user profiles. Test relative paths, absolute paths, missing directories, invalid path types, empty lists, and duplicate paths as configuration behavior.


## Template file rule

The source and packaged `templates/` tree contains deck files in the supported formats, template documentation, and required media assets. It does not contain `config.toml`. The user-wide template library may contain the same template files after setup. `init` selects one deck file and copies only that file plus required assets. Add acceptance checks that no packaged template directory contains `config.toml`, that setup creates `~/.graphcards/config.toml` and `~/.graphcards/templates/`, and that `init` leaves those user-wide files unchanged.

## Summary of Changes

Prepared GraphCards for distribution. Added release metadata, MIT licensing, package version reporting, root-template wheel resources, user-wide setup, ordered template path configuration, format-selective deck initialization, docs, resource and artifact tests, and final validation. The installed wheel was verified without the repository source tree.
