"""Scrambled-list entity-backed exercise generator."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import model_validator

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

FRONT_TEMPLATE = (
    "{{ target.label|default(target.front, true)|default(target.prompt, true)|"
    "default(target.question, true)|default(target.id, true) }}:\n"
    "{% for related_entity in scrambled_entities %}{{ loop.index }}. "
    "{{ related_entity.label|default(related_entity.back, true)|"
    "default(related_entity.answer, true)|default(related_entity.id, true) }}"
    "{% if not loop.last %}\n{% endif %}"
    "{% endfor %}"
)
BACK_TEMPLATE = (
    "{% for related_entity in ordered_entities %}{{ loop.index }}. "
    "{{ related_entity.label|default(related_entity.back, true)|"
    "default(related_entity.answer, true)|default(related_entity.id, true) }}"
    "{% if not loop.last %}\n{% endif %}"
    "{% endfor %}"
)


@ExerciseGenerator.register
class ScrambledListExerciseGenerator(ExerciseGenerator):
    """Generate one ordering exercise for each target entity."""

    type: Literal["scrambled_list"] = "scrambled_list"
    type_name = "scrambled_list"
    groups: dict[EntityId, EntityIdList]
    template_context_names: ClassVar[frozenset[str]] = frozenset(
        {"target", "scrambled_entities", "ordered_entities"}
    )

    @model_validator(mode="after")
    def validate_group_definitions(self) -> ScrambledListExerciseGenerator:
        if not self.groups:
            raise ValueError(f"generator {self.id!r} must define groups")
        for target_id, related_ids in self.groups.items():
            _nonblank(target_id)
            if len(related_ids) < 2:
                raise ValueError(
                    f"generator {self.id!r} target {target_id!r} needs at least two related "
                    "entities"
                )
            if len(related_ids) != len(set(related_ids)):
                raise ValueError(
                    f"generator {self.id!r} target {target_id!r} has duplicate related entities"
                )
            if target_id in related_ids:
                raise ValueError(
                    f"generator {self.id!r} target {target_id!r} cannot be one of its related "
                    "entities"
                )
        return self

    def validate_references(self, known_entity_ids: set[str]) -> None:
        _require_refs(self.id, self.groups.keys(), known_entity_ids, "target entity")
        for target_id, related_ids in self.groups.items():
            _require_refs(
                self.id,
                related_ids,
                known_entity_ids,
                f"related entity for target {target_id!r}",
            )

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(self.groups)

    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> Exercise:
        ordered_ids = self.groups[entity_id]
        scrambled_ids = list(ordered_ids)
        context.rng.shuffle(scrambled_ids)
        if tuple(scrambled_ids) == ordered_ids:
            scrambled_ids[0], scrambled_ids[1] = scrambled_ids[1], scrambled_ids[0]
        return ScrambledListExercise(
            card_key=self._key(entity_id, context.deck_id),
            generator_id=self.id,
            target_id=entity_id,
            ordered_ids=ordered_ids,
            scrambled_ids=tuple(scrambled_ids),
        )

    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        if not isinstance(exercise, ScrambledListExercise):
            raise PresentationError(f"generator {self.id!r} cannot render this exercise type")
        try:
            ordered_ids = self.groups[exercise.target_id]
            if exercise.card_key != self._key(exercise.target_id, context.deck_id):
                raise ValueError("exercise card identity does not match generator")
            if exercise.ordered_ids != ordered_ids:
                raise ValueError("exercise ordered IDs do not match generator configuration")
            if set(exercise.scrambled_ids) != set(ordered_ids):
                raise ValueError("exercise scrambled IDs do not match generator configuration")
            render_context = {
                "target": context.entities[exercise.target_id],
                "scrambled_entities": tuple(
                    context.entities[entity_id] for entity_id in exercise.scrambled_ids
                ),
                "ordered_entities": tuple(context.entities[entity_id] for entity_id in ordered_ids),
            }
            return CardView(
                card_key=exercise.card_key,
                front=_render_template(self.front_template or FRONT_TEMPLATE, render_context),
                back=_render_template(self.back_template or BACK_TEMPLATE, render_context),
            )
        except PresentationError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise PresentationError(
                f"generator {self.id!r} exercise is missing or inconsistent"
            ) from error


class ScrambledListExercise(Exercise):
    """Semantic ordering exercise before presentation rendering."""

    ordered_ids: tuple[EntityId, ...]
    scrambled_ids: tuple[EntityId, ...]

    @model_validator(mode="after")
    def validate_scrambled_list(self) -> ScrambledListExercise:
        if len(self.ordered_ids) < 2:
            raise ValueError("scrambled-list exercises require at least two related entities")
        if len(self.ordered_ids) != len(set(self.ordered_ids)):
            raise ValueError("scrambled-list ordered entities must be unique")
        if len(self.scrambled_ids) != len(self.ordered_ids):
            raise ValueError("scrambled-list exercise must contain every related entity")
        if len(self.scrambled_ids) != len(set(self.scrambled_ids)):
            raise ValueError("scrambled-list scrambled entities must be unique")
        if set(self.scrambled_ids) != set(self.ordered_ids):
            raise ValueError("scrambled-list orders must contain the same related entities")
        if self.scrambled_ids == self.ordered_ids:
            raise ValueError("scrambled-list exercise must change the related entity order")
        if self.target_id in self.ordered_ids:
            raise ValueError("scrambled-list target must not be one of its related entities")
        return self


__all__ = ["ScrambledListExercise", "ScrambledListExerciseGenerator"]
