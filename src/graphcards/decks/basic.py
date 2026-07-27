"""Basic entity-backed exercise generator."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import StrictStr

from graphcards.decks.base import (
    ExerciseGenerator,
    ExerciseGeneratorContext,
    _render_template,
    _require_refs,
)
from graphcards.errors import PresentationError
from graphcards.models import CardView, Exercise

FRONT_TEMPLATE = (
    "{{ entity.data.get('front', entity.data.get('prompt', "
    "entity.data.get('question', entity.id))) }}"
)
BACK_TEMPLATE = "{{ entity.data.get('back', entity.data.get('answer', entity.id)) }}"


@ExerciseGenerator.register
class BasicExerciseGenerator(ExerciseGenerator):
    type: Literal["basic"] = "basic"
    type_name = "basic"
    entities: tuple[StrictStr, ...]
    template_context_names: ClassVar[frozenset[str]] = frozenset({"entity"})

    def validate_references(self, known_entity_ids: set[str]) -> None:
        _require_refs(self.id, self.entities, known_entity_ids, "entity")
        if len(self.entities) != len(set(self.entities)):
            raise ValueError(f"generator {self.id!r} has duplicate target entities")

    @property
    def target_ids(self) -> tuple[str, ...]:
        return self.entities

    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> Exercise:
        key = self._key(entity_id, context.deck_id)
        return BasicExercise(card_key=key, generator_id=self.id, target_id=entity_id)

    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        if not isinstance(exercise, BasicExercise):
            raise PresentationError(f"generator {self.id!r} cannot render this exercise type")
        try:
            entity = context.entities[exercise.target_id]
            template_context = {"entity": entity}
        except (KeyError, TypeError) as error:
            raise PresentationError(
                f"generator {self.id!r} exercise references an unknown entity"
            ) from error
        return CardView(
            card_key=exercise.card_key,
            front=_render_template(self.front_template or FRONT_TEMPLATE, template_context),
            back=_render_template(self.back_template or BACK_TEMPLATE, template_context),
        )


class BasicExercise(Exercise):
    """Basic exercise identifying the entity whose data is rendered."""


__all__ = ["BasicExercise", "BasicExerciseGenerator"]
