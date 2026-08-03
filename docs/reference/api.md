# Python API reference

This page lists the supported public API. Import paths and signatures below are part of the
documented interface. Modules, names, and helpers that begin with `_` are internal and unsupported.

## Package version

```python
from graphcards import __version__, package_version
```

`package_version()` reads the installed `graphcards` distribution metadata. `__version__` is the
same value when the package is installed; a source-only import uses `0+unknown` until a distribution
is installed.

## Decks and exercise models

Import deck aggregates and generators from `graphcards.decks`:

```python
from graphcards.decks import (
    Deck,
    DeckDocument,
    Entity,
    EntityRenderValue,
    EntityGroup,
    ExerciseGenerator,
    ExerciseGeneratorContext,
    RenderConfig,
)
```

`Deck.load(path: str | Path) -> Deck` loads JSON, TOML, or YAML and validates the complete deck.
`Deck.generate_all(*, rng: random.Random | None = None) -> dict[str, Card]` creates semantic cards.
`Deck.generate(card_key: CardKey, *, rng: random.Random | None = None) -> Exercise` creates one
card, and `Deck.render(exercise: Exercise, *, rng: random.Random | None = None) -> CardView`
renders its front and back.

The public exercise types are:

`AnalogyExercise`, `AnalogyExerciseGenerator`, `BasicExercise`, `BasicExerciseGenerator`,
`CommonRelationExercise`, `CommonRelationExerciseGenerator`, `ClozeExercise`,
`ClozeExerciseGenerator`, `ClozeSelection`, `ImageOcclusionExercise`,
`ImageOcclusionExerciseGenerator`, `ImageOcclusionPlacement`, `MissingSequenceItemExercise`,
`MissingSequenceItemExerciseGenerator`, `MultipleChoiceExercise`,
`MultipleChoiceExerciseGenerator`, `OddOneOutExercise`, `OddOneOutExerciseGenerator`,
`OddOneOutRelation`, `ScrambledListExercise`, `ScrambledListExerciseGenerator`,
`TemporalComparisonExercise`, and `TemporalComparisonExerciseGenerator`.

The shared immutable models are in `graphcards.models`:

```python
from graphcards.models import Card, CardKey, CardView, Exercise, FrozenModel
```

`ExerciseGeneratorContext` contains `deck_id`, the entity mapping, and the operation RNG.
Generators implement `target_ids`, `validate_references`, `generate`, and `render`.

`RenderConfig` is the typed configuration for the optional generator `render` mapping. Its keys
are render slots declared by the exercise generator, and its values are direct top-level Entity
field names. Slot and field names must be public identifiers and cannot be blank, reserved,
dotted, or nested. An explicit slot replaces that generator's fallback chain; an omitted slot
uses the chain. The first present field wins, including an empty value. `EntityRenderValue` exposes `id`, ordinary Entity fields, and the resolved
generator-specific slots to Jinja as a frozen Pydantic model. A generator also exposes `render_entity()` and
`render_entities()` for custom render implementations.

Each exercise type owns its slot names and built-in templates. For example, `basic` uses
`question` and `answer`, `multiple_choice` uses `question`, `choice_label`, and `answer`, and
`scrambled_list` uses `target_label` and `item_label`. Templates receive type-specific contexts
such as `target`, `source`, `choice`, `related`, `candidate`, `comparison`, and `row`. Cloze
contexts expose `cloze_id`, `cloze_value`, `front`, and `back` directly; these remain derived from
`cloze_field`. Image paths and other generation
controls remain separate from `render`.

## References

```python
from graphcards.references import EntityId, EntityIdList, EntityIdListMarker, validate_entity_id
```

These types validate strict, non-blank entity IDs and mark generator fields that support named
group aliases.

## Configuration

```python
from graphcards.config import AppConfig, FsrsSettings, default_config_path, load_config
```

`default_config_path() -> Path` returns `~/.graphcards/config.toml`.
`load_config(path: str | Path | None = None) -> AppConfig` loads that path by default, resolves
relative paths from the TOML file, and translates malformed configuration into `ConfigError`.

`AppConfig` contains `display_timezone`, `decks`, `templates_paths`, and `fsrs`.
`templates_paths` is a non-empty ordered tuple of resolved directories. `FsrsSettings` validates
FSRS values and provides `create_scheduler()`.

## User setup and templates

```python
from pathlib import Path
from graphcards.scaffold import (
    TEMPLATE_FORMATS,
    available_templates,
    initialize_user_setup,
    initialize_workspace,
)
```

`initialize_user_setup(config_path: Path) -> Path` creates the config and copies the packaged
template library to the sibling `templates/` directory. It does not overwrite existing files.

`available_templates(template_paths: Sequence[Path] | None = None) -> tuple[str, ...]` lists unique
names in configured path order. `initialize_workspace(directory: Path, template: str | None = None,
deck_format: str = "json", template_paths: Sequence[Path] | None = None) -> Path` copies one
selected `deck.<format>` and the template's required assets. It does not copy configuration or
documentation files. When `template_paths` is omitted, the source checkout or installed package
resources are used.

## Generation and study services

```python
from graphcards.presentation import execute_cards, render_card
from graphcards.app import StudyService
```

`execute_cards` generates semantic cards and `render_card` renders one card. `StudyService`
coordinates generation, rendering, deck-file review-state persistence, FSRS scheduling, queue
planning, and reviews. Construct it with a `DeckFileStateStore`, an FSRS scheduler, and optional
RNG/time-zone values.

## Errors

```python
from graphcards.errors import (
    ConfigError,
    DailyLimitError,
    GraphCardsError,
    PresentationError,
    StaleReviewError,
    StorageError,
)
```

`GraphCardsError` is the base for user-facing failures. `ConfigError` covers invalid configuration,
deck files, and packaged template setup. `PresentationError` covers generation and rendering
failures. `StorageError` covers persistent state failures; `StaleReviewError` and
`DailyLimitError` are its specific review cases.

## Unsupported implementation details

The CLI parser helpers, private scaffold functions, Flask route handlers, and generator registry
storage are implementation details. Use the console commands and the public
classes and functions above instead of relying on those names.
