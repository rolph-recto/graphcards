"""Entity-backed cloze exercise generator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import StrictStr, field_validator, model_validator

from graphcards.decks.base import (
    Entity,
    ExerciseGenerator,
    ExerciseGeneratorContext,
    _nonblank,
    _render_template,
    _require_refs,
)
from graphcards.errors import PresentationError
from graphcards.models import CardKey, CardView, Exercise, FrozenModel
from graphcards.references import EntityId, validate_entity_id

HIDDEN_CLOZE = "[...]"


@dataclass(frozen=True, slots=True)
class _ClozeMarker:
    id: str
    content: tuple[str | _ClozeMarker, ...]


def _parse_clozes(sentence: str) -> tuple[str | _ClozeMarker, ...]:
    """Parse balanced cloze markers, including markers nested in an answer."""

    def parse_parts(index: int, *, nested: bool) -> tuple[tuple[str | _ClozeMarker, ...], int]:
        parts: list[str | _ClozeMarker] = []
        text_start = index
        while index < len(sentence):
            if sentence.startswith("]]", index):
                if not nested:
                    raise ValueError("unexpected cloze marker close")
                if text_start < index:
                    parts.append(sentence[text_start:index])
                return tuple(parts), index + 2
            if not sentence.startswith("[[", index):
                index += 1
                continue
            if text_start < index:
                parts.append(sentence[text_start:index])
            marker_start = index + 2
            separator = sentence.find("::", marker_start)
            opening = sentence.find("[[", marker_start)
            closing = sentence.find("]]", marker_start)
            if (
                separator < 0
                or (opening >= 0 and opening < separator)
                or (closing >= 0 and closing < separator)
            ):
                raise ValueError("invalid cloze marker header")
            marker_id = sentence[marker_start:separator]
            validate_entity_id(marker_id)
            content, index = parse_parts(separator + 2, nested=True)
            if not content:
                raise ValueError(f"cloze {marker_id!r} has a blank answer")
            parts.append(_ClozeMarker(marker_id, content))
            text_start = index
        if nested:
            raise ValueError("unclosed cloze marker")
        if text_start < index:
            parts.append(sentence[text_start:index])
        return tuple(parts), index

    parts, end = parse_parts(0, nested=False)
    if end != len(sentence):
        raise ValueError("invalid cloze marker")
    return parts


def _cloze_ids(parts: tuple[str | _ClozeMarker, ...]) -> tuple[str, ...]:
    ids: list[str] = []
    for part in parts:
        if isinstance(part, _ClozeMarker):
            ids.append(part.id)
            ids.extend(_cloze_ids(part.content))
    return tuple(ids)


def _render_clozes(parts: tuple[str | _ClozeMarker, ...], hidden_cloze_id: str | None) -> str:
    rendered: list[str] = []
    for part in parts:
        if isinstance(part, str):
            rendered.append(part)
        elif part.id == hidden_cloze_id:
            rendered.append(HIDDEN_CLOZE)
        else:
            rendered.append(_render_clozes(part.content, hidden_cloze_id))
    return "".join(rendered)


class ClozeSelection(FrozenModel):
    """One entity and the clozes selected from its configured sentence."""

    id: EntityId
    cloze_ids: tuple[EntityId, ...] | None = None

    @model_validator(mode="after")
    def validate_cloze_ids(self) -> ClozeSelection:
        if self.cloze_ids is not None:
            if not self.cloze_ids:
                raise ValueError(f"cloze selection for {self.id!r} must not be empty")
            if len(self.cloze_ids) != len(set(self.cloze_ids)):
                raise ValueError(f"cloze selection for {self.id!r} has duplicate cloze IDs")
        return self


@ExerciseGenerator.register
class ClozeExerciseGenerator(ExerciseGenerator):
    """Hide one marked answer in an entity field for each scheduled cloze."""

    type: Literal["cloze"] = "cloze"
    type_name = "cloze"
    entities: tuple[ClozeSelection, ...]
    cloze_field: StrictStr
    template_context_names: ClassVar[frozenset[str]] = frozenset(
        {"back", "cloze_id", "entity", "front"}
    )

    @field_validator("entities", mode="before")
    @classmethod
    def normalize_entity_selections(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            return value
        return [item if isinstance(item, Mapping) else {"id": item} for item in value]

    @field_validator("cloze_field")
    @classmethod
    def validate_cloze_field(cls, value: str) -> str:
        _nonblank(value)
        if value.startswith("_"):
            raise ValueError("cloze_field must name an ordinary entity field")
        return value

    @model_validator(mode="after")
    def validate_entity_selections(self) -> ClozeExerciseGenerator:
        if not self.entities:
            raise ValueError(f"generator {self.id!r} must define entities")
        entity_ids = tuple(selection.id for selection in self.entities)
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError(f"generator {self.id!r} has duplicate target entities")
        return self

    def validate_references(self, known_entity_ids: set[str]) -> None:
        _require_refs(self.id, self.target_ids, known_entity_ids, "entity")

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(selection.id for selection in self.entities)

    def _sentence(self, entity: Entity, entity_id: str) -> str:
        try:
            value = getattr(entity, self.cloze_field)
        except AttributeError as error:
            raise ValueError(
                f"generator {self.id!r} entity {entity_id!r} has no cloze field "
                f"{self.cloze_field!r}"
            ) from error
        if not isinstance(value, str):
            raise ValueError(
                f"generator {self.id!r} cloze field {self.cloze_field!r} for entity "
                f"{entity_id!r} must be a string"
            )
        return value

    def _markers(self, entity: Entity, entity_id: str) -> tuple[str | _ClozeMarker, ...]:
        sentence = self._sentence(entity, entity_id)
        try:
            markers = _parse_clozes(sentence)
        except ValueError as error:
            raise ValueError(
                f"generator {self.id!r} cloze field {self.cloze_field!r} for entity "
                f"{entity_id!r} is invalid: {error}"
            ) from error
        marker_ids = _cloze_ids(markers)
        if not marker_ids:
            raise ValueError(
                f"generator {self.id!r} cloze field {self.cloze_field!r} for entity "
                f"{entity_id!r} must contain at least one cloze marker"
            )
        if len(marker_ids) != len(set(marker_ids)):
            raise ValueError(f"entity {entity_id!r} contains duplicate cloze IDs")
        for marker in self._iter_markers(markers):
            if not _render_clozes(marker.content, None).strip():
                raise ValueError(f"entity {entity_id!r} contains a blank cloze answer")
        return markers

    @staticmethod
    def _iter_markers(
        parts: tuple[str | _ClozeMarker, ...],
    ) -> tuple[_ClozeMarker, ...]:
        markers: list[_ClozeMarker] = []
        for part in parts:
            if isinstance(part, _ClozeMarker):
                markers.append(part)
                markers.extend(ClozeExerciseGenerator._iter_markers(part.content))
        return tuple(markers)

    def _selected_cloze_ids(
        self, entity_id: str, entities: Mapping[str, Entity]
    ) -> tuple[str, ...]:
        try:
            entity = entities[entity_id]
        except KeyError as error:
            raise ValueError(f"generator {self.id!r} references unknown entity") from error
        selection = next((item for item in self.entities if item.id == entity_id), None)
        if selection is None:
            raise ValueError(
                f"generator {self.id!r} does not generate cloze for entity {entity_id!r}"
            )
        marker_ids = _cloze_ids(self._markers(entity, entity_id))
        selected_ids = selection.cloze_ids or marker_ids
        unknown = sorted(set(selected_ids).difference(marker_ids))
        if unknown:
            raise ValueError(
                f"generator {self.id!r} entity {entity_id!r} references unknown "
                f"cloze ID {unknown[0]!r}"
            )
        return selected_ids

    def scheduled_keys(self, entities: Mapping[str, Entity]) -> tuple[tuple[str, None], ...]:
        """Return one stable rendered cloze variant for each scheduled entity."""

        scheduled: list[tuple[str, None]] = []
        for selection in self.entities:
            self._selected_cloze_ids(selection.id, entities)
            scheduled.append((selection.id, None))
        return tuple(scheduled)

    def _exercise(
        self, entity_id: str, cloze_id: str, context: ExerciseGeneratorContext
    ) -> ClozeExercise:
        entity = context.entities.get(entity_id)
        if entity is None:
            raise PresentationError(f"generator {self.id!r} references an unknown entity")
        selection = next((item for item in self.entities if item.id == entity_id), None)
        if selection is None:
            raise PresentationError(
                f"generator {self.id!r} does not generate cloze for entity {entity_id!r}"
            )
        if cloze_id not in self._selected_cloze_ids(entity_id, context.entities):
            raise PresentationError(
                f"generator {self.id!r} does not generate cloze {cloze_id!r} for "
                f"entity {entity_id!r}"
            )
        return ClozeExercise(
            card_key=CardKey.exercise(context.deck_id, entity_id),
            generator_id=self.id,
            target_id=entity_id,
            cloze_id=cloze_id,
        )

    def generate(self, entity_id: str, context: ExerciseGeneratorContext) -> ClozeExercise:
        cloze_id = self._selected_cloze_ids(entity_id, context.entities)[0]
        return self._exercise(entity_id, cloze_id, context)

    def generate_card(self, card_key: CardKey, context: ExerciseGeneratorContext) -> ClozeExercise:
        return self.generate(card_key.entity_id, context)

    def validation_exercises(self, context: ExerciseGeneratorContext) -> tuple[ClozeExercise, ...]:
        return tuple(
            self.generate(entity_id, context)
            for entity_id, _cloze_id in self.scheduled_keys(context.entities)
        )

    def render(self, exercise: Exercise, context: ExerciseGeneratorContext) -> CardView:
        if not isinstance(exercise, ClozeExercise):
            raise PresentationError(f"generator {self.id!r} cannot render this exercise type")
        if exercise.card_key != CardKey.exercise(context.deck_id, exercise.target_id):
            raise PresentationError("cloze exercise card identity does not match generator")
        try:
            entity = context.entities[exercise.target_id]
            markers = self._markers(entity, exercise.target_id)
            front = _render_clozes(markers, exercise.cloze_id)
            back = _render_clozes(markers, None)
            template_context = {
                "back": back,
                "cloze_id": exercise.cloze_id,
                "entity": entity,
                "front": front,
            }
            return CardView(
                card_key=exercise.card_key,
                front=_render_template(self.front_template, template_context)
                if self.front_template is not None
                else front,
                back=_render_template(self.back_template, template_context)
                if self.back_template is not None
                else back,
            )
        except PresentationError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise PresentationError(
                f"generator {self.id!r} cloze exercise is missing or inconsistent"
            ) from error


class ClozeExercise(Exercise):
    """Semantic cloze exercise with one selected hidden marker."""

    cloze_id: EntityId


__all__ = ["ClozeExercise", "ClozeExerciseGenerator", "ClozeSelection"]
