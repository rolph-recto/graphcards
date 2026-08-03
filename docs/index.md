# GraphCards documentation

GraphCards keeps user configuration in `~/.graphcards/config.toml` and user templates in
`~/.graphcards/templates/`. A separate setup command creates those files. A deck directory holds
deck content and any assets that the deck needs.

Choose a guide:

- [Getting started](tutorials/getting-started.md) — install GraphCards, set up a profile, create and
  register a deck, and start studying.
- [Add entities and generators](tutorials/add-entities-and-generators.md) — author JSON, TOML,
  and YAML decks and validate references.
- [Create an exercise type](how-to/create-exercise-type.md) — extend GraphCards with a generator
  and exercise model.
- [Python API reference](reference/api.md) — supported import paths, models, configuration, and
  error types.

## Command summary

```console
graphcards setup
graphcards templates
graphcards init DECK_DIRECTORY --template NAME --format json
graphcards validate
graphcards status
graphcards serve
```

Put `--config PATH` before the command to use a configuration other than the default. The
`templates_paths` list is required to be non-empty and ordered. Each relative entry is resolved
from the directory containing the configuration file.
