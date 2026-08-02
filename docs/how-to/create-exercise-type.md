# Create an exercise type

This guide describes the supported extension path for a contributor. It uses behavior tests and
the existing generator registry. The current implementation keeps generator modules under
`src/graphcards/decks/`.

## Define the model and generator

Create a Pydantic v2 model that extends `Exercise` and a generator that extends
`ExerciseGenerator`:

```python
from graphcards.decks import ExerciseGenerator
from graphcards.models import CardView, Exercise

class ExampleExercise(Exercise):
    answer: str

class ExampleGenerator(ExerciseGenerator):
    type_name = "example"
    template_context_names = frozenset({"target"})

    @property
    def target_ids(self) -> tuple[str, ...]:
        return ("target-id",)

    def generate(self, entity_id, context):
        return ExampleExercise(
            card_key=self._key(entity_id, context.deck_id),
            generator_id=self.id,
            target_id=entity_id,
            answer=context.entities[entity_id].label,
        )

    def render(self, exercise, context) -> CardView:
        return CardView(
            card_key=exercise.card_key,
            front=exercise.answer,
            back=exercise.answer,
        )
```

Use strict fields and validators for configuration. Implement `validate_references` for every
entity or group reference. Store all values needed for rendering in the semantic exercise so
rendering remains stateless and does not sample new data.

## Register and export it

Decorate the generator with `@ExerciseGenerator.register`. Import the module from
`graphcards.decks.__init__` so registration occurs when the public package is imported. Add the
exercise and generator to `__all__` and export any public supporting types from their documented
module.

The deck loader dispatches an exercise envelope by its `type` field. The `type_name` must match
that value. Unknown types become a user-facing `ConfigError` during `Deck.load`.

## Validate, generate, and render

Add an example deck in JSON, TOML, and YAML. Test all of the following behavior:

1. Valid configuration loads and references resolve.
2. Unknown entity and group references fail with a `ConfigError`.
3. `generate` creates a stable `CardKey`, generator ID, target ID, and exercise payload.
4. `render` returns a `CardView` for the front and back.
5. Custom templates accept only the declared `template_context_names`.
6. Repeated rendering does not change the semantic exercise.

Use deterministic RNG input in tests when the type samples or shuffles data. Run the full behavior
test suite:

```console
uv run pytest -W error tests/test_your_exercise.py
uv run ruff check .
```

Do not document registry internals, private helper functions, or storage implementation details as
stable API. See the [API reference](../reference/api.md) for supported imports.
