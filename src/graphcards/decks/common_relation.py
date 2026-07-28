"""Entity-backed common-relation completion exercise generator."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import ClassVar, Literal

from pydantic import Field, StrictInt, StrictStr, ValidationError, model_validator

from graphcards.decks.base import (
    ExerciseGenerator,
    ExerciseGeneratorContext,
    _nonblank,
    _render_template,
    _require_refs,
)
from graphcards.errors import PresentationError
from graphcards.models import CardView, Exercise

FRONT_TEMPLATE = (
    "{% for related_entity in related_entities %}"
    "{{ related_entity.label|default(related_entity.back)|"
    "default(related_entity.answer)|default(related_entity.id) }} — ?"
    "{% if not loop.last %}\n{% endif %}"
    "{% endfor %}"
)
BACK_TEMPLATE = "{{ target.label|default(target.back)|default(target.answer)|default(target.id) }}"


@ExerciseGenerator.register
class CommonRelationExerciseGenerator(ExerciseGenerator):
    type: Literal["common_relation"] = "common_relation"
    type_name = "common_relation"
    relations: dict[StrictStr, tuple[StrictStr, ...]]
    min_examples: StrictInt = Field(default=2, ge=2)
    max_related: StrictInt = Field(default=0, ge=0)
    template_context_names: ClassVar[frozenset[str]] = frozenset({"target", "related_entities"})

    @model_validator(mode="before")
    @classmethod
    def validate_raw_target_ids(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        raw_relations = value.get("relations")
        if isinstance(raw_relations, Mapping):
            for target_id, raw_related in raw_relations.items():
                _nonblank(target_id)
                if isinstance(raw_related, (list, tuple)):
                    for related_id in raw_related:
                        _nonblank(related_id)
        return value

    @model_validator(mode="after")
    def validate_relation_definitions(self) -> CommonRelationExerciseGenerator:
        if not self.relations:
            raise ValueError(f"generator {self.id!r} must define relations")
        for target_id, related in self.relations.items():
            _nonblank(target_id)
            if len(related) < self.min_examples:
                raise ValueError(
                    f"generator {self.id!r} target {target_id!r} must have at least "
                    f"{self.min_examples} related entities"
                )
            if len(related) != len(set(related)):
                raise ValueError(
                    f"generator {self.id!r} target {target_id!r} has duplicate related entities"
                )
        if self.max_related and self.max_related < self.min_examples:
            raise ValueError(
                f"generator {self.id!r} max_related must be zero or at least min_examples"
            )
        return self

    def validate_references(self, known_entity_ids: set[str]) -> None:
        for target_id, group in self.relations.items():
            _require_refs(self.id, (target_id,), known_entity_ids, "target entity")
            _require_refs(
                self.id,
                group,
                known_entity_ids,
                f"related entity for target {target_id!r}",
            )

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(self.relations)

    def _selected_related_ids(
        self, entity_id: str, context: ExerciseGeneratorContext
    ) -> tuple[str, ...]:
        related = self.relations[entity_id]
        if self.max_related == 0 or self.max_related >= len(related):
            return related
        selected = set(context.rng.sample(related, self.max_related))
        return tuple(related_id for related_id in related if related_id in selected)

    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> Exercise:
        key = self._key(entity_id, context.deck_id)
        return CommonRelationExercise(
            card_key=key,
            generator_id=self.id,
            target_id=entity_id,
            related_ids=self._selected_related_ids(entity_id, context),
        )

    def _validation_related_ids(self, related: tuple[str, ...]) -> Iterator[tuple[str, ...]]:
        if self.max_related == 0 or self.max_related >= len(related):
            yield related
            return
        cap = self.max_related
        starts = list(range(0, len(related) - cap + 1, cap))
        last_start = len(related) - cap
        if starts[-1] != last_start:
            starts.append(last_start)
        yielded: set[tuple[str, ...]] = set()
        for start in starts:
            selected = related[start : start + cap]
            if selected not in yielded:
                yielded.add(selected)
                yield selected

    def validation_exercises(self, context: ExerciseGeneratorContext) -> tuple[Exercise, ...]:
        return tuple(
            CommonRelationExercise(
                card_key=self._key(target_id, context.deck_id),
                generator_id=self.id,
                target_id=target_id,
                related_ids=related_ids,
            )
            for target_id, related in self.relations.items()
            for related_ids in self._validation_related_ids(related)
        )

    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        if not isinstance(exercise, CommonRelationExercise):
            raise PresentationError(f"generator {self.id!r} cannot render this exercise type")
        try:
            related = self.relations[exercise.target_id]
            expected_count = (
                len(related) if self.max_related == 0 else min(self.max_related, len(related))
            )
            if not isinstance(exercise.related_ids, tuple) or not all(
                isinstance(related_id, str) for related_id in exercise.related_ids
            ):
                raise ValueError("exercise related IDs must be a tuple of strings")
            if len(exercise.related_ids) != expected_count:
                raise ValueError("exercise has the wrong number of related entities")
            if len(exercise.related_ids) != len(set(exercise.related_ids)):
                raise ValueError("exercise has duplicate related entities")
            if not set(exercise.related_ids).issubset(related):
                raise ValueError("exercise contains an unconfigured related entity")
            if exercise.card_key != self._key(exercise.target_id, context.deck_id):
                raise ValueError("exercise card identity does not match generator")
            target = context.entities[exercise.target_id]
            related_entities = tuple(
                context.entities[related_id] for related_id in exercise.related_ids
            )
            render_context = {
                "target": target,
                "related_entities": related_entities,
            }
            return CardView(
                card_key=exercise.card_key,
                front=_render_template(self.front_template or FRONT_TEMPLATE, render_context),
                back=_render_template(self.back_template or BACK_TEMPLATE, render_context),
            )
        except PresentationError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError, ValidationError) as error:
            raise PresentationError(
                f"generator {self.id!r} exercise is missing or inconsistent"
            ) from error


class CommonRelationExercise(Exercise):
    """Semantic common-relation exercise before presentation rendering."""

    related_ids: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def validate_relation_payload(self) -> CommonRelationExercise:
        for related_id in self.related_ids:
            _nonblank(related_id)
        if len(self.related_ids) < 2:
            raise ValueError("common-relation exercises require at least two related entities")
        if len(self.related_ids) != len(set(self.related_ids)):
            raise ValueError("common-relation exercises require unique related entities")
        return self


__all__ = [
    "CommonRelationExercise",
    "CommonRelationExerciseGenerator",
]
