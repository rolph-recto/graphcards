"""Study-session orchestration across JSON/TOML/YAML decks, SQLite, and FSRS."""

from __future__ import annotations

import random
from datetime import datetime

from fsrs import Rating, Scheduler

from graphcards.decks import Deck
from graphcards.errors import PresentationError
from graphcards.models import Card, CardView
from graphcards.presentation import execute_cards, render_card
from graphcards.storage import Repository, StoredCard, datetime_as_utc, utc_now


class StudyService:
    """Coordinate graph rendering, persistent state, and FSRS reviews."""

    def __init__(
        self,
        repository: Repository,
        scheduler: Scheduler,
        rng: random.Random | None = None,
    ) -> None:
        self.repository = repository
        self.scheduler = scheduler
        self.rng = rng or random.Random()

    def sync(self, deck: Deck, now: datetime | None = None) -> tuple[int, int]:
        cards = self.generate_all(deck)
        return self.repository.sync_deck(deck.name, cards, now or utc_now())

    def generate_all(self, deck: Deck) -> dict[str, Card]:
        """Generate every current semantic exercise from one validated deck."""

        return execute_cards(deck, rng=self.rng)

    def render_all(self, deck: Deck) -> dict[str, CardView]:
        """Generate and render all current cards at the application boundary."""

        return {
            card_id: render_card(deck, card) for card_id, card in self.generate_all(deck).items()
        }

    def render(self, deck: Deck, stored_card: StoredCard) -> CardView:
        cards = execute_cards(deck, stored_card.card_key, rng=self.rng)
        card = cards.get(stored_card.card_id)
        if card is None:
            raise PresentationError(
                f"deck {deck.name!r} no longer generates card {stored_card.card_id}"
            )
        return render_card(deck, card)

    def suspend(
        self,
        deck: Deck,
        card_id: str,
        reason: str | None = None,
    ) -> None:
        """Suspend one membership without changing its global FSRS card."""

        self.repository.suspend_card(deck.name, card_id, reason)

    def resume(self, deck: Deck, card_id: str) -> None:
        """Resume one membership at its existing global FSRS schedule."""

        self.repository.resume_card(deck.name, card_id)

    def review(
        self,
        deck: Deck,
        card: StoredCard,
        rating: Rating,
        now: datetime | None = None,
    ) -> StoredCard:
        if card.card_key.deck_id != deck.name:
            raise PresentationError(f"card {card.card_id} does not belong to deck {deck.name!r}")
        review_time = datetime_as_utc(now or utc_now())
        source_card = card.card()
        previous_interval_seconds = (
            (
                datetime_as_utc(source_card.due) - datetime_as_utc(source_card.last_review)
            ).total_seconds()
            if source_card.last_review is not None
            else None
        )
        retrievability = (
            self.scheduler.get_card_retrievability(
                source_card,
                current_datetime=review_time,
            )
            if source_card.stability is not None and source_card.last_review is not None
            else None
        )
        updated_card, review_log = self.scheduler.review_card(
            source_card, rating, review_datetime=review_time
        )
        card_json = self.repository.save_review(
            card.card_id,
            deck.name,
            card.card_json,
            updated_card,
            review_log,
            previous_interval_seconds=previous_interval_seconds,
            retrievability=retrievability,
        )
        return StoredCard(
            card_id=card.card_id,
            card_key=card.card_key,
            card_json=card_json,
        )
