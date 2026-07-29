"""Entity-backed odd-one-out exercise generator."""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import ClassVar, Literal

from pydantic import Field, StrictInt, ValidationError, model_validator

from graphcards.decks.base import (
    ExerciseGenerator,
    ExerciseGeneratorContext,
    _nonblank,
    _render_template,
    _require_refs,
)
from graphcards.errors import PresentationError
from graphcards.models import CardView, Exercise, FrozenModel
from graphcards.references import EntityId, EntityIdList

FRONT_TEMPLATE = (
    "{{ target.label|default(target.back, true)|default(target.answer, true)|"
    "default(target.id, true) }}:\n"
    "{% for candidate in candidate_entities %}"
    "{{ candidate.label|default(candidate.back, true)|default(candidate.answer, true)|"
    "default(candidate.id, true) }} — ?"
    "{% if not loop.last %}\n{% endif %}"
    "{% endfor %}"
)
BACK_TEMPLATE = (
    "{{ odd_entity.label|default(odd_entity.back, true)|default(odd_entity.answer, true)|"
    "default(odd_entity.id, true) }}"
)


class OddOneOutRelation(FrozenModel):
    """Common and odd entity pools for one target entity."""

    common: EntityIdList
    odd: EntityIdList

    @model_validator(mode="after")
    def validate_entity_pools(self) -> OddOneOutRelation:
        if not self.common:
            raise ValueError("odd-one-out common entities must not be empty")
        if not self.odd:
            raise ValueError("odd-one-out odd entities must not be empty")
        if len(self.common) != len(set(self.common)):
            raise ValueError("odd-one-out common entities must be unique")
        if len(self.odd) != len(set(self.odd)):
            raise ValueError("odd-one-out odd entities must be unique")
        overlap = sorted(set(self.common).intersection(self.odd))
        if overlap:
            raise ValueError(
                f"odd-one-out common and odd entities must be exclusive; overlap: {overlap[0]!r}"
            )
        return self


@ExerciseGenerator.register
class OddOneOutExerciseGenerator(ExerciseGenerator):
    """Generate one odd-entity selection exercise for each target entity."""

    type: Literal["odd_one_out"] = "odd_one_out"
    type_name = "odd_one_out"
    relations: dict[EntityId, OddOneOutRelation]
    min_candidates: StrictInt = Field(default=3, ge=3)
    max_candidates: StrictInt = Field(default=0, ge=0)
    template_context_names: ClassVar[frozenset[str]] = frozenset(
        {"candidate_entities", "common_entities", "odd_entity", "target"}
    )

    @model_validator(mode="before")
    @classmethod
    def validate_raw_relation_ids(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        raw_relations = value.get("relations")
        if isinstance(raw_relations, Mapping):
            for target_id, raw_relation in raw_relations.items():
                _nonblank(target_id)
                if isinstance(raw_relation, Mapping):
                    for field_name in ("common", "odd"):
                        raw_ids = raw_relation.get(field_name)
                        if isinstance(raw_ids, str):
                            _nonblank(raw_ids)
                        elif isinstance(raw_ids, (list, tuple)):
                            for entity_id in raw_ids:
                                _nonblank(entity_id)
        return value

    @model_validator(mode="after")
    def validate_relation_definitions(self) -> OddOneOutExerciseGenerator:
        if not self.relations:
            raise ValueError(f"generator {self.id!r} must define relations")
        if self.max_candidates and self.max_candidates < self.min_candidates:
            raise ValueError(
                f"generator {self.id!r} max_candidates must be zero or at least min_candidates"
            )
        for target_id, relation in self.relations.items():
            _nonblank(target_id)
            if len(relation.common) < self.min_candidates - 1:
                raise ValueError(
                    f"generator {self.id!r} target {target_id!r} must have at least "
                    f"{self.min_candidates - 1} common entities"
                )
        return self

    def validate_references(self, known_entity_ids: set[str]) -> None:
        for target_id, relation in self.relations.items():
            _require_refs(self.id, (target_id,), known_entity_ids, "target entity")
            _require_refs(
                self.id,
                relation.common,
                known_entity_ids,
                f"common entity for target {target_id!r}",
            )
            _require_refs(
                self.id,
                relation.odd,
                known_entity_ids,
                f"odd entity for target {target_id!r}",
            )

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(self.relations)

    def _build_exercise(
        self,
        entity_id: str,
        odd_id: str,
        context: ExerciseGeneratorContext,
    ) -> OddOneOutExercise:
        relation = self.relations[entity_id]
        if self.max_candidates and self.max_candidates < len(relation.common) + 1:
            selected_common = tuple(context.rng.sample(relation.common, self.max_candidates - 1))
        else:
            selected_common = relation.common
        candidate_ids = [*selected_common, odd_id]
        context.rng.shuffle(candidate_ids)
        return OddOneOutExercise(
            card_key=self._key(entity_id, context.deck_id),
            generator_id=self.id,
            target_id=entity_id,
            common_ids=selected_common,
            candidate_ids=tuple(candidate_ids),
            odd_id=odd_id,
        )

    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> Exercise:
        relation = self.relations[entity_id]
        return self._build_exercise(entity_id, context.rng.choice(relation.odd), context)

    def validation_exercises(self, context: ExerciseGeneratorContext) -> tuple[Exercise, ...]:
        validation_context = ExerciseGeneratorContext(
            context.deck_id, context.entities, random.Random(0)
        )
        return tuple(
            self._build_exercise(target_id, odd_id, validation_context)
            for target_id, relation in self.relations.items()
            for odd_id in relation.odd
        )

    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        if not isinstance(exercise, OddOneOutExercise):
            raise PresentationError(f"generator {self.id!r} cannot render this exercise type")
        try:
            relation = self.relations[exercise.target_id]
            expected_count = (
                len(relation.common) + 1
                if self.max_candidates == 0
                else min(self.max_candidates, len(relation.common) + 1)
            )
            if exercise.card_key != self._key(exercise.target_id, context.deck_id):
                raise ValueError("exercise card identity does not match generator")
            if exercise.odd_id not in relation.odd:
                raise ValueError("exercise contains an unconfigured odd entity")
            if len(exercise.common_ids) != expected_count - 1:
                raise ValueError("exercise has the wrong number of common entities")
            if len(exercise.common_ids) != len(set(exercise.common_ids)):
                raise ValueError("exercise has duplicate common entities")
            if not set(exercise.common_ids).issubset(relation.common):
                raise ValueError("exercise contains an unconfigured common entity")
            if len(exercise.candidate_ids) != expected_count:
                raise ValueError("exercise has the wrong number of candidates")
            if len(exercise.candidate_ids) != len(set(exercise.candidate_ids)):
                raise ValueError("exercise has duplicate candidates")
            expected_ids = set(exercise.common_ids) | {exercise.odd_id}
            if set(exercise.candidate_ids) != expected_ids:
                raise ValueError("exercise candidates do not match its common and odd entities")
            target = context.entities[exercise.target_id]
            common_entities = tuple(
                context.entities[entity_id] for entity_id in exercise.common_ids
            )
            candidate_entities = tuple(
                context.entities[entity_id] for entity_id in exercise.candidate_ids
            )
            odd_entity = context.entities[exercise.odd_id]
            render_context = {
                "candidate_entities": candidate_entities,
                "common_entities": common_entities,
                "odd_entity": odd_entity,
                "target": target,
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


class OddOneOutExercise(Exercise):
    """Semantic odd-one-out exercise before presentation rendering."""

    common_ids: tuple[EntityId, ...]
    candidate_ids: tuple[EntityId, ...]
    odd_id: EntityId

    @model_validator(mode="after")
    def validate_relation_payload(self) -> OddOneOutExercise:
        if len(self.common_ids) < 1:
            raise ValueError("odd-one-out exercises require at least one common entity")
        if len(self.common_ids) != len(set(self.common_ids)):
            raise ValueError("odd-one-out common entities must be unique")
        if len(self.candidate_ids) < 2:
            raise ValueError("odd-one-out exercises require at least two candidates")
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("odd-one-out candidates must be unique")
        if self.odd_id in self.common_ids:
            raise ValueError("odd-one-out common and odd entities must be exclusive")
        if self.odd_id not in self.candidate_ids:
            raise ValueError("odd-one-out answer must be one of the candidates")
        if set(self.candidate_ids) != set(self.common_ids) | {self.odd_id}:
            raise ValueError("odd-one-out candidates must contain the common entities and answer")
        return self


__all__ = [
    "OddOneOutExercise",
    "OddOneOutExerciseGenerator",
    "OddOneOutRelation",
]
