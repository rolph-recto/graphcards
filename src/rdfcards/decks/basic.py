"""Basic front/back decks."""

from __future__ import annotations

from collections import defaultdict

from rdflib.term import Identifier

from rdfcards.decks.base import DeckDefinition, Presentation
from rdfcards.errors import PresentationError
from rdfcards.models import CardKey


class BasicPresentation(Presentation):
    """A front/back presentation that the student rates manually."""


class BasicDeck(DeckDefinition):
    """Configured basic front/back query behavior."""

    config_name = "basic"
    required_variables = frozenset({"front", "back"})

    def group(
        self,
        result: object,
        *,
        expected: set[str],
        card_key: CardKey | None = None,
    ) -> dict[str, Presentation]:
        del card_key
        grouped: dict[CardKey, set[tuple[Identifier, Identifier]]] = defaultdict(set)
        for row_number, row in enumerate(result, start=1):  # type: ignore[arg-type]
            values = self._row_values(row)
            self._require_bound(values, expected, row_number)
            key = self._card_key(values, row_number)
            grouped[key].add((values["front"], values["back"]))

        presentations: list[Presentation] = []
        for key, pairs in grouped.items():
            if len(pairs) != 1:
                raise PresentationError(
                    f"deck {self.name!r} returns conflicting front/back values for card "
                    f"{key.digest}"
                )
            front, back = next(iter(pairs))
            presentations.append(BasicPresentation(card_key=key, front=front, back=back))
        return self._by_digest(presentations)
