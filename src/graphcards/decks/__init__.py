"""Registered deck definitions and generated presentation models."""

from graphcards.decks.analogy import AnalogyDeck, AnalogyPresentation
from graphcards.decks.base import (
    DEFAULT_MAX_CHOICES,
    DEFAULT_WINDOW_SIZE,
    DeckDefinition,
    Presentation,
)
from graphcards.decks.basic import BasicDeck, BasicPresentation
from graphcards.decks.multiple_choice import (
    ChoiceOption,
    MultipleChoiceDeck,
    MultipleChoicePresentation,
)
from graphcards.decks.ordered_list import (
    OrderedListDeck,
    OrderedListPresentation,
    OrderedListRow,
)

__all__ = [
    "DEFAULT_MAX_CHOICES",
    "DEFAULT_WINDOW_SIZE",
    "AnalogyDeck",
    "AnalogyPresentation",
    "BasicDeck",
    "BasicPresentation",
    "ChoiceOption",
    "DeckDefinition",
    "MultipleChoiceDeck",
    "MultipleChoicePresentation",
    "OrderedListDeck",
    "OrderedListPresentation",
    "OrderedListRow",
    "Presentation",
]
