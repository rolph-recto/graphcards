"""Stable in-memory browser study sessions."""

from __future__ import annotations

import random
import secrets
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus

from fsrs import Rating

from rdfcards.app import StudyService
from rdfcards.config import DeckDefinition
from rdfcards.errors import PresentationError, StaleReviewError
from rdfcards.storage import StoredCard, utc_now


class StudyMode(StrEnum):
    DUE = "due"
    FORGOTTEN = "forgotten"
    PRACTICE = "practice"
    AHEAD = "ahead"

    @property
    def label(self) -> str:
        return {
            StudyMode.DUE: "Due cards",
            StudyMode.FORGOTTEN: "Review forgotten",
            StudyMode.PRACTICE: "Practice deck",
            StudyMode.AHEAD: "Review ahead",
        }[self]


class RequestFailure(Exception):
    """A safe HTTP failure raised by web study state transitions."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class CurrentCard:
    card: StoredCard
    front: str
    back: str
    revealed: bool = False


class StudySession:
    """Own one stable, sequential browser study session."""

    def __init__(
        self,
        deck: DeckDefinition,
        service: StudyService,
        cards: list[StoredCard],
        mode: StudyMode,
        days: int,
        requested_limit: int,
        rng: random.Random,
    ) -> None:
        self.deck = deck
        self.service = service
        self.cards = tuple(cards)
        self.mode = mode
        self.days = days
        self.requested_limit = requested_limit
        self.rng = rng
        self.session_token = secrets.token_urlsafe(32)
        self.index = 0
        self.completed_count = 0
        self.suspended_count = 0
        self.skipped: list[str] = []
        self.current: CurrentCard | None = None
        self._load_current()

    @property
    def complete(self) -> bool:
        return self.current is None

    @property
    def is_practice(self) -> bool:
        return self.mode is StudyMode.PRACTICE

    def _load_current(self) -> None:
        while self.index < len(self.cards):
            card = self.cards[self.index]
            if not self.service.repository.card_available(self.deck.name, card.card_id):
                if self.service.repository.card_suspended(self.deck.name, card.card_id):
                    self.suspended_count += 1
                self.index += 1
                continue
            try:
                presentation = self.service.render(self.deck, card)
                front = presentation.front_text(self.rng)
            except PresentationError as error:
                self.skipped.append(f"{card.card_id}: {error}")
                self.index += 1
                continue
            self.current = CurrentCard(
                card=card,
                front=front,
                back=str(presentation.back),
            )
            return
        self.current = None

    def _require_current(self, session_token: str, card_id: str) -> CurrentCard:
        if not secrets.compare_digest(session_token, self.session_token):
            raise RequestFailure(HTTPStatus.FORBIDDEN, "This study form is not valid.")
        self.refresh_availability()
        if self.current is None:
            raise RequestFailure(HTTPStatus.CONFLICT, "This study session is already complete.")
        if card_id != self.current.card.card_id:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "That card is no longer current. Reload the study page and try again.",
            )
        return self.current

    def reveal(self, session_token: str, card_id: str) -> None:
        current = self._require_current(session_token, card_id)
        if current.revealed:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "The answer to this card is already revealed.",
            )
        current.revealed = True

    def rate(self, session_token: str, card_id: str, rating: Rating) -> None:
        current = self._require_current(session_token, card_id)
        if self.is_practice:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "Practice cards do not update scheduling.",
            )
        if not current.revealed:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "Reveal the answer before rating this card.",
            )
        try:
            self.service.review(self.deck, current.card, rating, utc_now())
        except StaleReviewError as error:
            refreshed = self.service.repository.get_card(current.card.card_id)
            if refreshed is None:
                self.skipped.append("A card was removed after this study session started.")
                self.index += 1
                self.current = None
                self._load_current()
                message = "This card is no longer available. Continue with the next card."
            else:
                current.card = refreshed
                message = "This card was reviewed elsewhere. Reload the study page and try again."
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                message,
            ) from error
        self._advance()

    def next_practice(self, session_token: str, card_id: str) -> None:
        current = self._require_current(session_token, card_id)
        if not self.is_practice:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "Only practice sessions use the Next action.",
            )
        if not current.revealed:
            raise RequestFailure(
                HTTPStatus.CONFLICT,
                "Reveal the answer before continuing.",
            )
        self._advance()

    def suspend(self, session_token: str, card_id: str, reason: str | None) -> None:
        current = self._require_current(session_token, card_id)
        self.service.suspend(self.deck, current.card.card_id, reason)
        self._advance(completed=False, suspended=True)

    def refresh_availability(self) -> None:
        """Drop a current card suspended or removed after session creation."""

        if self.current is None or self.service.repository.card_available(
            self.deck.name,
            self.current.card.card_id,
        ):
            return
        self.current = None
        self._load_current()

    def _advance(self, *, completed: bool = True, suspended: bool = False) -> None:
        if completed:
            self.completed_count += 1
        if suspended:
            self.suspended_count += 1
        self.index += 1
        self.current = None
        self._load_current()


def completion_summary(session: StudySession) -> tuple[str, str]:
    if session.cards:
        title = "Session complete"
        verb = "Practiced" if session.is_practice else "Reviewed"
        summary = f"{verb} {session.completed_count} card(s)."
    elif session.mode is StudyMode.DUE:
        title, summary = "You’re all caught up", "No cards are due in this deck."
    elif session.mode is StudyMode.FORGOTTEN:
        title = "No forgotten cards"
        summary = f"No cards were rated Again in the last {session.days} day(s)."
    elif session.mode is StudyMode.PRACTICE:
        title, summary = "Nothing to practice", "This deck has no available cards."
    else:
        title = "Nothing due soon"
        summary = f"No cards are due in the next {session.days} day(s)."
    if session.skipped:
        summary += f" Skipped {len(session.skipped)} card(s) that could not be presented."
    if session.suspended_count:
        summary += f" Suspended {session.suspended_count} card(s)."
    return title, summary
