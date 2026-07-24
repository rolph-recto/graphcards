"""Registered deck definitions, semantic cards, and rendering contracts."""

from graphcards.decks.analogy import AnalogyCard, AnalogyDeck
from graphcards.decks.base import (
    DEFAULT_MAX_CHOICES,
    DEFAULT_WINDOW_SIZE,
    DeckDefinition,
    TemplateSource,
)
from graphcards.decks.basic import BasicCard, BasicDeck
from graphcards.decks.multiple_choice import (
    MultipleChoiceCard,
    MultipleChoiceDeck,
)
from graphcards.decks.ordered_list import (
    OrderedListCard,
    OrderedListDeck,
    OrderedListRow,
)

__all__ = [
    "DEFAULT_MAX_CHOICES",
    "DEFAULT_WINDOW_SIZE",
    "AnalogyCard",
    "AnalogyDeck",
    "BasicCard",
    "BasicDeck",
    "DeckDefinition",
    "MultipleChoiceCard",
    "MultipleChoiceDeck",
    "OrderedListCard",
    "OrderedListDeck",
    "OrderedListRow",
    "TemplateSource",
]
