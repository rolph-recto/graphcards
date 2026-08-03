# Getting started

This tutorial creates one study profile and one deck. The commands work with an installed wheel
and do not require the GraphCards source checkout.

## Install and set up a profile

Build or obtain a wheel, then install it in a Python 3.14 environment:

```console
python -m pip install dist/graphcards-*.whl
```

Create the user-owned configuration and template library:

```console
graphcards setup
```

The command creates:

```text
~/.graphcards/
  config.toml
  templates/
```

The generated configuration contains an ordered, non-empty template path:

```toml
templates_paths = ["templates"]
```

The installation does not create or modify this directory. `graphcards templates` lists the unique
template names from the configured directories.

## Create one deck

Choose a destination outside the Python environment and initialize one template:

```console
graphcards init ~/graphcards-study/capitals --template capitals --format json
```

The command copies only `deck.json` for this invocation. An image-based template also copies its
required `assets/` files. It does not copy a README, another deck format, a `templates/` directory,
or `config.toml`. It does not register the deck.

Use `--format toml` or `--format yaml` when you want the other supported deck formats.

## Register and validate the deck

Add the deck path to the user-wide configuration as a separate step. For example:

```toml
templates_paths = ["templates"]
decks = ["../graphcards-study/capitals/deck.json"]
```

The path is relative to `~/.graphcards/config.toml`. An absolute path is also valid. Then run:

```console
graphcards validate
graphcards status --full
```

`validate` loads the complete deck, checks entity and generator references, renders deterministic
examples, and reports the card count. `status` initializes or refreshes review state as needed,
then reports queue counts and daily limits.

## Start a study session

Run the local Flask interface:

```console
graphcards serve
```

Open the local address printed by the command. Reviews update the review state in the deck file.

## Use another profile

For tests or a second profile, pass an explicit configuration path before the command:

```console
graphcards --config /tmp/graphcards-profile/config.toml templates
graphcards --config /tmp/graphcards-profile/config.toml init /tmp/my-deck --template cloze
graphcards --config /tmp/graphcards-profile/config.toml validate
```

If multiple template directories contain the same name, the first entry in `templates_paths` wins.
Missing directories are valid configuration entries and simply contribute no templates until they
exist.
