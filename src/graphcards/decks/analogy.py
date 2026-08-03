"""Entity-backed analogy exercise generator."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import model_validator

from graphcards.decks.base import (
    ExerciseGenerator,
    ExerciseGeneratorContext,
    _render_template,
    _require_refs,
)
from graphcards.errors import PresentationError
from graphcards.models import CardView, Exercise
from graphcards.references import EntityId, EntityIdList

FRONT_TEMPLATE = "{{ source.question }} is to {{ source.answer }} as {{ target.question }} is to ?"
BACK_TEMPLATE = "{{ target.answer }}"


@ExerciseGenerator.register
class AnalogyExerciseGenerator(ExerciseGenerator):
    type: Literal["analogy"] = "analogy"
    type_name = "analogy"
    sources: dict[EntityId, EntityIdList]
    template_context_names: ClassVar[frozenset[str]] = frozenset({"source", "target"})
    render_fields: ClassVar[dict[str, tuple[str, ...]]] = {
        "question": ("front", "prompt", "question", "id"),
        "answer": ("back", "answer", "label", "id"),
    }

    @model_validator(mode="after")
    def validate_source_ids(self) -> AnalogyExerciseGenerator:
        for target_id, source_ids in self.sources.items():
            if not source_ids:
                raise ValueError(
                    f"generator {self.id!r} target {target_id!r} must define at least one source"
                )
            if len(source_ids) != len(set(source_ids)):
                raise ValueError(
                    f"generator {self.id!r} target {target_id!r} has duplicate sources"
                )
            if target_id in source_ids:
                raise ValueError(
                    f"generator {self.id!r} target {target_id!r} cannot use itself as a source"
                )
        return self

    def validate_references(self, known_entity_ids: set[str]) -> None:
        if not self.sources:
            raise ValueError(f"generator {self.id!r} must define analogy sources")
        _require_refs(self.id, self.sources.keys(), known_entity_ids, "target entity")
        for target_id, source_ids in self.sources.items():
            _require_refs(self.id, source_ids, known_entity_ids, f"source for target {target_id!r}")

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(self.sources)

    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> Exercise:
        key = self._key(entity_id, context.deck_id)
        source_id = context.rng.choice(self.sources[entity_id])
        if source_id not in context.entities or entity_id not in context.entities:
            raise PresentationError(f"generator {self.id!r} references an unknown analogy entity")
        return AnalogyExercise(
            card_key=key,
            generator_id=self.id,
            target_id=entity_id,
            source_id=source_id,
        )

    def validation_exercises(self, context: ExerciseGeneratorContext) -> tuple[Exercise, ...]:
        return tuple(
            AnalogyExercise(
                card_key=self._key(target_id, context.deck_id),
                generator_id=self.id,
                target_id=target_id,
                source_id=source_id,
            )
            for target_id, source_ids in self.sources.items()
            for source_id in source_ids
        )

    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        if not isinstance(exercise, AnalogyExercise):
            raise PresentationError(f"generator {self.id!r} cannot render this exercise type")
        try:
            source = context.entities[exercise.source_id]
            target = context.entities[exercise.target_id]
            render_source = self.render_entity(source)
            render_target = self.render_entity(target)
            template_context = {
                "source": render_source,
                "target": render_target,
            }
            return CardView(
                card_key=exercise.card_key,
                front=_render_template(self.front_template or FRONT_TEMPLATE, template_context),
                back=_render_template(self.back_template or BACK_TEMPLATE, template_context),
            )
        except (KeyError, TypeError) as error:
            raise PresentationError(
                f"generator {self.id!r} exercise references an unknown entity"
            ) from error


class AnalogyExercise(Exercise):
    source_id: EntityId

    @model_validator(mode="after")
    def validate_source(self) -> AnalogyExercise:
        if self.source_id == self.target_id:
            raise ValueError("analogy source and target must be different entities")
        return self


__all__ = ["AnalogyExercise", "AnalogyExerciseGenerator"]
