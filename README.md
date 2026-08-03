# GraphCards

GraphCards is a local flashcard application for entity-backed exercises. It loads JSON, TOML, or
YAML decks, generates semantic cards, and stores FSRS study state in each deck file. The
application runs locally and includes a Flask web study interface.

## Install

Install a built wheel in a Python 3.14 environment:

```console
python -m pip install dist/graphcards-*.whl
```

The installed package includes the built-in deck templates and the `graphcards` console script.

## First study session

Create the user-wide configuration and template library once:

```console
graphcards setup
graphcards templates
```

Create one deck in a chosen directory. Initialization copies one selected deck format and any
required assets. It does not copy a README, a `templates/` directory, or a user configuration:

```console
graphcards init ~/graphcards-study/capitals --template capitals --format json
```

Add the deck to `~/.graphcards/config.toml`:

```toml
templates_paths = ["templates"]
decks = ["../graphcards-study/capitals/deck.json"]
```

Then validate, inspect status, and start the local web interface:

```console
graphcards validate
graphcards status
graphcards serve
```

Use `--config PATH` for another user profile or for a test configuration. Relative
`templates_paths` and `decks` entries are resolved from that configuration file. The first
template directory that contains a matching name wins.

## Decks

A deck contains entities and exercise generators. The supported generator types are `basic`,
`multiple_choice`, `missing_sequence_item`, `scrambled_list`, `analogy`, `cloze`,
`image_occlusion`, `common_relation`, `odd_one_out`, and `temporal_comparison`.

See the documentation for deck examples, generator references, extension guidance, and the
supported Python API:

- [Documentation index](docs/index.md)
- [Getting started](docs/tutorials/getting-started.md)
- [Add entities and generators](docs/tutorials/add-entities-and-generators.md)
- [Create an exercise type](docs/how-to/create-exercise-type.md)
- [API reference](docs/reference/api.md)

## Development

GraphCards uses `uv`. Run the complete local checks with:

```console
uv run pytest -W error
uv run ruff check .
uv run ruff format --check .
uv build
```

GraphCards is distributed under the [MIT License](LICENSE).
