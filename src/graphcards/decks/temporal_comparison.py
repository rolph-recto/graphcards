"""Temporal comparison exercise generator."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import StrictInt, model_validator

from graphcards.decks.base import (
    ExerciseGenerator,
    ExerciseGeneratorContext,
    _render_template,
    _require_refs,
)
from graphcards.errors import PresentationError
from graphcards.models import CardView, Exercise
from graphcards.references import EntityId, EntityIdList

FRONT_TEMPLATE = "Did {{ target.event_label }} happen before or after {{ comparison.event_label }}?"
BACK_TEMPLATE = "{{ answer }}"


@ExerciseGenerator.register
class TemporalComparisonExerciseGenerator(ExerciseGenerator):
    """Generate one before-or-after exercise for each event in an ordered group."""

    type: Literal["temporal_comparison"] = "temporal_comparison"
    type_name = "temporal_comparison"
    groups: dict[EntityId, EntityIdList]
    template_context_names: ClassVar[frozenset[str]] = frozenset(
        {
            "answer",
            "comparison",
            "comparison_position",
            "group",
            "target",
            "target_position",
        }
    )
    render_fields: ClassVar[dict[str, tuple[str, ...]]] = {
        "event_label": ("label", "back", "answer", "id"),
    }

    @model_validator(mode="after")
    def validate_group_definitions(self) -> TemporalComparisonExerciseGenerator:
        if not self.groups:
            raise ValueError(f"generator {self.id!r} must define groups")
        members: set[str] = set()
        for group_id, group_members in self.groups.items():
            if not group_id.strip():
                raise ValueError("temporal-comparison group IDs must be non-blank strings")
            if len(group_members) < 2:
                raise ValueError(
                    f"generator {self.id!r} group {group_id!r} needs at least two events"
                )
            if len(group_members) != len(set(group_members)):
                raise ValueError(f"generator {self.id!r} group {group_id!r} has duplicate events")
            if group_id in group_members:
                raise ValueError(
                    f"generator {self.id!r} group {group_id!r} cannot contain its group entity"
                )
            overlap = members.intersection(group_members)
            if overlap:
                event_id = sorted(overlap)[0]
                raise ValueError(
                    f"generator {self.id!r} event {event_id!r} belongs to multiple groups"
                )
            members.update(group_members)
        return self

    def validate_references(self, known_entity_ids: set[str]) -> None:
        for group_id, group_members in self.groups.items():
            _require_refs(self.id, (group_id,), known_entity_ids, "group entity")
            _require_refs(self.id, group_members, known_entity_ids, "event entity")

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(event_id for members in self.groups.values() for event_id in members)

    def _group_for(self, entity_id: str) -> tuple[str, tuple[str, ...]]:
        for group_id, members in self.groups.items():
            if entity_id in members:
                return group_id, members
        raise PresentationError(
            f"generator {self.id!r} has no temporal group for entity {entity_id!r}"
        )

    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> Exercise:
        group_id, members = self._group_for(entity_id)
        comparison_id = context.rng.choice(
            tuple(member for member in members if member != entity_id)
        )
        return TemporalComparisonExercise(
            card_key=self._key(entity_id, context.deck_id),
            generator_id=self.id,
            target_id=entity_id,
            group_id=group_id,
            comparison_id=comparison_id,
            target_position=members.index(entity_id) + 1,
            comparison_position=members.index(comparison_id) + 1,
        )

    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        if not isinstance(exercise, TemporalComparisonExercise):
            raise PresentationError(f"generator {self.id!r} cannot render this exercise type")
        try:
            group_members = self.groups[exercise.group_id]
            if exercise.card_key != self._key(exercise.target_id, context.deck_id):
                raise ValueError("exercise card identity does not match generator")
            if exercise.target_id not in group_members:
                raise ValueError("exercise target is not in its temporal group")
            if exercise.comparison_id not in group_members:
                raise ValueError("exercise comparison is not in its temporal group")
            if exercise.target_id == exercise.comparison_id:
                raise ValueError("exercise target and comparison must be different")
            if exercise.target_position != group_members.index(exercise.target_id) + 1:
                raise ValueError("exercise target position does not match its temporal group")
            if exercise.comparison_position != group_members.index(exercise.comparison_id) + 1:
                raise ValueError("exercise comparison position does not match its temporal group")
            if exercise.target_position == exercise.comparison_position:
                raise ValueError("exercise positions must be different")
            render_target = self.render_entity(context.entities[exercise.target_id])
            render_comparison = self.render_entity(context.entities[exercise.comparison_id])
            render_group = self.render_entity(context.entities[exercise.group_id])
            render_context = {
                "answer": exercise.answer,
                "comparison": render_comparison,
                "comparison_position": exercise.comparison_position,
                "group": render_group,
                "target": render_target,
                "target_position": exercise.target_position,
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


class TemporalComparisonExercise(Exercise):
    """Stored temporal comparison data before presentation rendering."""

    group_id: EntityId
    comparison_id: EntityId
    target_position: StrictInt
    comparison_position: StrictInt

    @model_validator(mode="after")
    def validate_temporal_comparison(self) -> TemporalComparisonExercise:
        if self.target_id == self.comparison_id:
            raise ValueError("temporal comparison entities must be different")
        if self.target_position < 1 or self.comparison_position < 1:
            raise ValueError("temporal comparison positions must be 1 or greater")
        if self.target_position == self.comparison_position:
            raise ValueError("temporal comparison positions must be different")
        return self

    @property
    def answer(self) -> Literal["before", "after"]:
        if self.target_position == self.comparison_position:
            raise ValueError("temporal comparison positions must be different")
        return "before" if self.target_position < self.comparison_position else "after"


__all__ = ["TemporalComparisonExercise", "TemporalComparisonExerciseGenerator"]
