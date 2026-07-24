"""Ordered-list completion decks and presentations."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Annotated
from typing import Literal as TypingLiteral

from pydantic import Field, ValidationError, field_validator, model_validator
from rdflib import Literal, URIRef
from rdflib.term import Identifier

from rdfcards.decks.base import (
    DEFAULT_WINDOW_SIZE,
    DeckDefinition,
    Presentation,
)
from rdfcards.errors import PresentationError
from rdfcards.models import CardKey, RdfModel, TargetKind, validation_message


class OrderedListRow(RdfModel):
    """One validated row in an ordered-list query result."""

    entity: URIRef
    group: Identifier
    position: Annotated[int, Field(strict=True, ge=1)]
    label: Identifier


class OrderedListPresentation(Presentation):
    """A presentation that hides one member of a non-cyclic ordered list."""

    ordered_rows: tuple[OrderedListRow, ...] = Field(exclude=True, repr=False)
    hidden_position: Annotated[int, Field(strict=True, ge=1)] = Field(exclude=True)
    window_size: Annotated[int, Field(strict=True, ge=0)] = Field(exclude=True)

    @staticmethod
    def _window(
        rows: tuple[OrderedListRow, ...],
        hidden_position: int,
        window_size: int,
    ) -> str:
        if window_size == 0 or window_size >= len(rows):
            visible = rows
            omitted_before = omitted_after = False
        else:
            target_index = hidden_position - 1
            start = max(0, target_index - window_size // 2)
            start = min(start, len(rows) - window_size)
            end = start + window_size
            visible = rows[start:end]
            omitted_before = start > 0
            omitted_after = end < len(rows)

        lines: list[str] = []
        if omitted_before:
            lines.append("…")
        lines.extend(
            f"{row.position}. {'?' if row.position == hidden_position else row.label}"
            for row in visible
        )
        if omitted_after:
            lines.append("…")
        return "\n".join(lines)

    @classmethod
    def from_rows(
        cls,
        *,
        card_key: CardKey,
        rows: list[OrderedListRow],
        hidden: OrderedListRow,
        window_size: int,
    ) -> OrderedListPresentation:
        """Build one card while retaining the list data that determines its display."""

        ordered_rows = tuple(sorted(rows, key=lambda row: row.position))
        return cls(
            card_key=card_key,
            front=Literal(cls._window(ordered_rows, hidden.position, window_size)),
            back=hidden.label,
            ordered_rows=ordered_rows,
            hidden_position=hidden.position,
            window_size=window_size,
        )

    @model_validator(mode="after")
    def validate_ordered_list(self) -> OrderedListPresentation:
        if len(self.ordered_rows) < 2:
            raise ValueError("must contain at least two rows")
        positions = [row.position for row in self.ordered_rows]
        expected_positions = list(range(1, len(self.ordered_rows) + 1))
        if positions != expected_positions:
            reason = "unique" if len(set(positions)) != len(positions) else "contiguous 1-based"
            raise ValueError(f"must have {reason} positions")
        groups = {row.group for row in self.ordered_rows}
        if len(groups) != 1:
            raise ValueError("rows must belong to one group")
        if self.hidden_position > len(self.ordered_rows):
            raise ValueError("hidden position must identify an ordered-list row")

        hidden = self.ordered_rows[self.hidden_position - 1]
        if self.card_key != CardKey.entity(hidden.entity):
            raise ValueError("hidden row must match the presentation card identity")
        expected_front = Literal(
            self._window(self.ordered_rows, self.hidden_position, self.window_size)
        )
        if self.front != expected_front or self.back != hidden.label:
            raise ValueError("front and back must match the hidden ordered-list row")
        return self

    def front_text(self, rng: random.Random) -> str:
        """Render the retained window, hiding this presentation's target row."""

        del rng
        return self._window(self.ordered_rows, self.hidden_position, self.window_size)


class OrderedListDeck(DeckDefinition):
    """Configured ordered-list completion query behavior."""

    config_name = "ordered_list"
    required_variables = frozenset({"group", "position", "label"})
    uses_card_bindings = False
    exact_projection = ("entity", "group", "position", "label")

    target: TypingLiteral[TargetKind.ENTITY]
    window_size: Annotated[int, Field(strict=True, ge=0)] = DEFAULT_WINDOW_SIZE

    @field_validator("target", mode="before")
    @classmethod
    def require_entity_target(cls, value: object) -> object:
        if value not in (TargetKind.ENTITY, TargetKind.ENTITY.value):
            raise ValueError("ordered_list decks must target entity cards")
        return value

    def _position(self, value: Identifier, row_number: int) -> int:
        return self._rdf_integer(
            value,
            variable="position",
            minimum=1,
            minimum_description="at least 1",
            row_number=row_number,
        )

    def _row(
        self,
        values: dict[str, Identifier],
        *,
        row_number: int,
    ) -> OrderedListRow:
        try:
            return OrderedListRow(
                entity=values["entity"],
                group=values["group"],
                position=self._position(values["position"], row_number),
                label=values["label"],
            )
        except PresentationError:
            raise
        except ValidationError as error:
            raise PresentationError(
                f"deck {self.name!r} row {row_number} has an invalid ordered-list row: "
                f"{validation_message(error)}"
            ) from error

    def group(
        self,
        result: object,
        *,
        expected: set[str],
        card_key: CardKey | None = None,
    ) -> dict[str, Presentation]:
        rows_by_group: dict[Identifier, list[OrderedListRow]] = defaultdict(list)
        entity_groups: dict[URIRef, Identifier] = {}
        entity_keys: dict[URIRef, CardKey] = {}
        for row_number, row in enumerate(result, start=1):  # type: ignore[arg-type]
            values = self._row_values(row)
            self._require_bound(values, expected, row_number)
            key = self._card_key(values, row_number)
            parsed = self._row(values, row_number=row_number)
            existing_group = entity_groups.get(parsed.entity)
            if existing_group is not None:
                if existing_group != parsed.group:
                    raise PresentationError(
                        f"deck {self.name!r} entity {parsed.entity.n3()} belongs to multiple "
                        "ordered-list groups"
                    )
                raise PresentationError(
                    f"deck {self.name!r} returns duplicate ordered-list rows for "
                    f"entity {parsed.entity.n3()}"
                )
            entity_groups[parsed.entity] = parsed.group
            entity_keys[parsed.entity] = key
            rows_by_group[parsed.group].append(parsed)

        presentations: list[Presentation] = []
        for group, group_rows in rows_by_group.items():
            try:
                group_presentations = [
                    OrderedListPresentation.from_rows(
                        card_key=entity_keys[row.entity],
                        rows=group_rows,
                        hidden=row,
                        window_size=self.window_size,
                    )
                    for row in sorted(group_rows, key=lambda item: item.position)
                ]
            except ValidationError as error:
                raise PresentationError(
                    f"deck {self.name!r} ordered-list group {group.n3()} "
                    f"{validation_message(error)}"
                ) from error
            presentations.extend(
                presentation
                for presentation in group_presentations
                if card_key is None or presentation.card_key == card_key
            )

        if card_key is not None and not presentations:
            raise PresentationError(
                f"deck {self.name!r} ordered-list query does not contain card {card_key.digest}"
            )
        return self._by_digest(presentations)
