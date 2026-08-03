"""Target-centered entity-backed multiple-choice generator."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import Field, StrictInt, model_validator

from graphcards.decks.base import (
    ExerciseGenerator,
    ExerciseGeneratorContext,
    _nonblank,
    _render_template,
    _require_refs,
)
from graphcards.errors import PresentationError
from graphcards.models import CardView, Exercise
from graphcards.references import EntityId, EntityIdList

DEFAULT_MAX_CHOICES = 4
FRONT_TEMPLATE = (
    "{{ target.question }}"
    "{% for choice in choice_entities %}\n  {{ loop.index }}. "
    "{{ choice.choice_label }}"
    "{% endfor %}"
)
BACK_TEMPLATE = "{{ target.answer }}"


@ExerciseGenerator.register
class MultipleChoiceExerciseGenerator(ExerciseGenerator):
    type: Literal["multiple_choice"] = "multiple_choice"
    type_name = "multiple_choice"
    choices: dict[EntityId, EntityIdList]
    max_choices: Annotated[StrictInt, Field(default=DEFAULT_MAX_CHOICES, ge=2)]
    template_context_names: ClassVar[frozenset[str]] = frozenset(
        {"target", "choice", "choices", "choice_entities"}
    )
    render_fields: ClassVar[dict[str, tuple[str, ...]]] = {
        "question": ("front", "prompt", "question", "id"),
        "choice_label": ("label", "back", "answer", "id"),
        "answer": ("label", "back", "answer", "id"),
    }

    @model_validator(mode="after")
    def validate_pool_ids(self) -> MultipleChoiceExerciseGenerator:
        for target_id, pool in self.choices.items():
            _nonblank(target_id)
            for entity_id in pool:
                _nonblank(entity_id)
        return self

    def validate_references(self, known_entity_ids: set[str]) -> None:
        if not self.choices:
            raise ValueError(f"generator {self.id!r} must define choices")
        for target_id, pool in self.choices.items():
            _require_refs(self.id, (target_id,), known_entity_ids, "target entity")
            _require_refs(self.id, pool, known_entity_ids, f"choices for target {target_id!r}")
            if len(pool) != len(set(pool)):
                raise ValueError(f"generator {self.id!r} has duplicate choices")
            if len(pool) < 1:
                raise ValueError(
                    f"generator {self.id!r} choices for target {target_id!r} must contain at least "
                    "one distractor"
                )
            if target_id in pool:
                raise ValueError(
                    f"generator {self.id!r} target {target_id!r} cannot be in its distractor pool"
                )

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(self.choices)

    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> Exercise:
        key = self._key(entity_id, context.deck_id)
        pool = list(self.choices[entity_id])
        context.rng.shuffle(pool)
        choices = [entity_id, *pool[: self.max_choices - 1]]
        context.rng.shuffle(choices)
        return MultipleChoiceExercise(
            card_key=key,
            generator_id=self.id,
            target_id=entity_id,
            choices=tuple(choices),
        )

    def validation_exercises(self, context: ExerciseGeneratorContext) -> tuple[Exercise, ...]:
        """Cover every configured choice entity during deterministic render preflight."""

        exercises: list[MultipleChoiceExercise] = []
        pool_size = self.max_choices - 1
        for target_id, pool in self.choices.items():
            chunks = (
                (pool,)
                if len(pool) <= pool_size
                else tuple(
                    pool[start : start + pool_size] for start in range(0, len(pool), pool_size)
                )
            )
            for chunk in chunks:
                exercises.append(
                    MultipleChoiceExercise(
                        card_key=self._key(target_id, context.deck_id),
                        generator_id=self.id,
                        target_id=target_id,
                        choices=(target_id, *chunk),
                    )
                )
        return tuple(exercises)

    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        if not isinstance(exercise, MultipleChoiceExercise):
            raise PresentationError(f"generator {self.id!r} cannot render this exercise type")
        try:
            target = context.entities[exercise.target_id]
            render_target = self.render_entity(target)
            choice_entities = self.render_entities(context.entities, exercise.choices)
            render_context = {
                "target": render_target,
                "choice": choice_entities,
                "choices": choice_entities,
                "choice_entities": choice_entities,
            }
            front_template = self.front_template or FRONT_TEMPLATE
            back_template = self.back_template or BACK_TEMPLATE
            return CardView(
                card_key=exercise.card_key,
                front=_render_template(front_template, render_context),
                back=_render_template(back_template, render_context),
            )
        except (KeyError, TypeError) as error:
            raise PresentationError(
                f"generator {self.id!r} exercise references an unknown entity"
            ) from error


class MultipleChoiceExercise(Exercise):
    """Multiple-choice exercise identifying the target entity to render."""

    choices: tuple[EntityId, ...]

    @model_validator(mode="after")
    def validate_choices(self) -> MultipleChoiceExercise:
        if len(self.choices) < 2 or len(set(self.choices)) != len(self.choices):
            raise ValueError("multiple-choice choices must contain at least two unique entities")
        if self.target_id not in self.choices:
            raise ValueError("multiple-choice target must be one of its choices")
        return self


__all__ = [
    "MultipleChoiceExercise",
    "MultipleChoiceExerciseGenerator",
]
