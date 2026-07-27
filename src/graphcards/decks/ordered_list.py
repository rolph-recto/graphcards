"""Ordered-list entity-backed exercise generator."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import StrictInt, StrictStr, model_validator

from graphcards.decks.base import (
    ExerciseGenerator,
    ExerciseGeneratorContext,
    _render_template,
    _require_refs,
)
from graphcards.errors import PresentationError
from graphcards.models import CardView, Exercise

DEFAULT_WINDOW_SIZE = 5
FRONT_TEMPLATE = (
    "{% if omitted_before %}…\n{% endif %}"
    "{% for row in rows %}{{ row.position }}. "
    "{% if row.is_target %}?{% else %}"
    "{{ row.entity.data.get('label', row.entity.data.get('back', "
    "row.entity.data.get('answer', row.entity.id))) }}"
    "{% endif %}"
    "{% if not loop.last or omitted_after %}\n{% endif %}"
    "{% endfor %}{% if omitted_after %}…{% endif %}"
)
BACK_TEMPLATE = (
    "{{ target.data.get('label', target.data.get('back', target.data.get('answer', target.id))) }}"
)


@ExerciseGenerator.register
class OrderedListExerciseGenerator(ExerciseGenerator):
    type: Literal["ordered_list"] = "ordered_list"
    type_name = "ordered_list"
    groups: dict[StrictStr, tuple[StrictStr, ...]]
    window_size: StrictInt = DEFAULT_WINDOW_SIZE
    template_context_names: ClassVar[frozenset[str]] = frozenset(
        {"target", "ordered_entities", "rows", "omitted_before", "omitted_after"}
    )

    @model_validator(mode="after")
    def validate_group_ids(self) -> OrderedListExerciseGenerator:
        for group_id, members in self.groups.items():
            if not group_id.strip():
                raise ValueError("ordered-list group IDs must be non-blank strings")
            for member in members:
                if not member.strip():
                    raise ValueError("ordered-list members must be non-blank strings")
        return self

    @model_validator(mode="after")
    def validate_window_size(self) -> OrderedListExerciseGenerator:
        if self.window_size < 0:
            raise ValueError("ordered-list window_size must be zero or greater")
        return self

    def validate_references(self, known_entity_ids: set[str]) -> None:
        if not self.groups:
            raise ValueError(f"generator {self.id!r} must define groups")
        members: set[str] = set()
        for group_id, group_members in self.groups.items():
            _require_refs(self.id, (group_id,), known_entity_ids, "group")
            _require_refs(self.id, group_members, known_entity_ids, "group member")
            if len(group_members) < 2:
                raise ValueError(
                    f"generator {self.id!r} group {group_id!r} needs at least two members"
                )
            if len(group_members) != len(set(group_members)):
                raise ValueError(f"generator {self.id!r} group {group_id!r} has duplicate members")
            overlap = members.intersection(group_members)
            if overlap:
                raise ValueError(
                    f"generator {self.id!r} member {sorted(overlap)[0]!r} belongs to multiple "
                    "groups"
                )
            members.update(group_members)

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(member for members in self.groups.values() for member in members)

    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> Exercise:
        key = self._key(entity_id, context.deck_id)
        for group_id, members in self.groups.items():
            if entity_id in members:
                return OrderedListExercise(
                    card_key=key,
                    generator_id=self.id,
                    target_id=entity_id,
                    group_id=group_id,
                    ordered_ids=members,
                )
        raise PresentationError(f"generator {self.id!r} has no group for entity {entity_id!r}")

    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        if not isinstance(exercise, OrderedListExercise):
            raise PresentationError(f"generator {self.id!r} cannot render this exercise type")
        try:
            target_index = exercise.ordered_ids.index(exercise.target_id)
            if self.window_size == 0 or self.window_size >= len(exercise.ordered_ids):
                visible_start = 0
                visible_end = len(exercise.ordered_ids)
            else:
                visible_start = max(0, target_index - self.window_size // 2)
                visible_start = min(
                    visible_start,
                    len(exercise.ordered_ids) - self.window_size,
                )
                visible_end = visible_start + self.window_size
            visible_ids = exercise.ordered_ids[visible_start:visible_end]
            render_context = {
                "target": context.entities[exercise.target_id],
                "ordered_entities": tuple(
                    context.entities[member] for member in exercise.ordered_ids
                ),
                "rows": tuple(
                    {
                        "position": index + visible_start + 1,
                        "entity": context.entities[member],
                        "is_target": member == exercise.target_id,
                    }
                    for index, member in enumerate(visible_ids)
                ),
                "omitted_before": visible_start > 0,
                "omitted_after": visible_end < len(exercise.ordered_ids),
            }
            return CardView(
                card_key=exercise.card_key,
                front=_render_template(self.front_template or FRONT_TEMPLATE, render_context),
                back=_render_template(self.back_template or BACK_TEMPLATE, render_context),
            )
        except (KeyError, TypeError) as error:
            raise PresentationError(
                f"generator {self.id!r} exercise references an unknown entity"
            ) from error


class OrderedListExercise(Exercise):
    group_id: StrictStr
    ordered_ids: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def validate_ordered_list(self) -> OrderedListExercise:
        if self.target_id not in self.ordered_ids:
            raise ValueError("ordered-list target must be one of its members")
        if len(self.ordered_ids) < 2 or len(set(self.ordered_ids)) != len(self.ordered_ids):
            raise ValueError("ordered-list members must be unique and contain at least two items")
        return self


__all__ = ["OrderedListExercise", "OrderedListExerciseGenerator"]
