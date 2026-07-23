from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fsrs import Rating
from rdflib import URIRef

from rdfcards.app import StudyService
from rdfcards.config import AppConfig, DeckDefinition
from rdfcards.decks import Basic
from rdfcards.errors import PresentationError, StorageError
from rdfcards.models import CardKey, TargetKind
from rdfcards.presentation import execute_presentations, load_graph
from rdfcards.storage import Repository


def app_for(config: AppConfig, repository: Repository) -> StudyService:
    return StudyService(load_graph(config.sources), repository, config.fsrs.create_scheduler())


def test_sync_is_idempotent_and_entities_are_shared_across_decks(config: AppConfig) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        basic = config.deck("capitals-basic")
        basic_copy = DeckDefinition(
            name="capitals-basic-copy",
            kind=basic.kind,
            query_path=basic.query_path,
            target=basic.target,
        )
        assert app.sync(basic, now) == (2, 2)
        assert app.sync(basic, now) == (2, 0)
        assert app.sync(basic_copy, now) == (2, 0)
        choice = config.deck("capitals-choice")
        choice_copy = DeckDefinition(
            name="capitals-choice-copy",
            kind=choice.kind,
            query_path=choice.query_path,
            target=choice.target,
        )
        assert app.sync(choice, now) == (2, 2)
        assert app.sync(choice_copy, now) == (2, 0)
        card_count = repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        association_count = repository.connection.execute(
            "SELECT COUNT(*) FROM deck_cards WHERE active = 1"
        ).fetchone()[0]
        assert card_count == 4
        assert association_count == 8

        reviewed = repository.due_cards(choice.name, now, 1)[0]
        app.review(choice, reviewed, Rating.Good, now)
        copy_due = {card.card_id for card in repository.due_cards(choice_copy.name, now, None)}
        assert reviewed.card_id not in copy_due

        reviewed_triple = repository.due_cards(basic.name, now, 1)[0]
        app.review(basic, reviewed_triple, Rating.Good, now)
        triple_copy_due = {
            card.card_id for card in repository.due_cards(basic_copy.name, now, None)
        }
        assert reviewed_triple.card_id not in triple_copy_due


def test_removed_and_restored_triple_keeps_schedule(config: AppConfig, workspace: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, now)
        card = repository.due_cards(deck.name, now, 1)[0]
        app.review(deck, card, Rating.Good, now)
        reviewed_json = repository.get_card(card.card_id).card_json  # type: ignore[union-attr]

        source = workspace / "data" / "knowledge.ttl"
        original = source.read_text(encoding="utf-8")
        source.write_text(original.replace(" ex:capital ", " ex:note "), encoding="utf-8")
        removed_app = app_for(config, repository)
        removed_app.sync(deck, now + timedelta(seconds=1))
        active = repository.connection.execute(
            "SELECT active FROM deck_cards WHERE deck_name = ? AND card_id = ?",
            (deck.name, card.card_id),
        ).fetchone()[0]
        assert active == 0

        source.write_text(original, encoding="utf-8")
        restored_app = app_for(config, repository)
        restored_app.sync(deck, now + timedelta(seconds=2))
        restored = repository.get_card(card.card_id)
        assert restored is not None
        assert restored.card_json == reviewed_json


def test_editing_a_triple_creates_a_new_card(config: AppConfig, workspace: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        original_app = app_for(config, repository)
        original_app.sync(deck, now)
        original_ids = {
            row[0]
            for row in repository.connection.execute(
                "SELECT card_id FROM deck_cards WHERE deck_name = ? AND active = 1",
                (deck.name,),
            )
        }

        source = workspace / "data" / "knowledge.ttl"
        content = source.read_text(encoding="utf-8")
        source.write_text(
            content.replace("ex:France ex:capital ex:Paris", "ex:France ex:capital ex:Berlin"),
            encoding="utf-8",
        )
        edited_app = app_for(config, repository)
        assert edited_app.sync(deck, now + timedelta(seconds=1)) == (2, 1)
        active_ids = {
            row[0]
            for row in repository.connection.execute(
                "SELECT card_id FROM deck_cards WHERE deck_name = ? AND active = 1",
                (deck.name,),
            )
        }
        assert len(active_ids - original_ids) == 1
        assert len(original_ids - active_ids) == 1
        assert repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 3


def test_render_reruns_query_for_current_metadata(config: AppConfig, workspace: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        original_app = app_for(config, repository)
        presentations = execute_presentations(original_app.graph, deck)
        france = next(
            presentation
            for presentation in presentations.values()
            if presentation.card_key.target_kind is TargetKind.TRIPLE
            and str(presentation.card_key.terms[0]).endswith("France")
        )
        original_app.sync(deck, now)
        stored = repository.get_card(france.card_key.digest)
        assert stored is not None

        source = workspace / "data" / "knowledge.ttl"
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                'rdfs:label "France"', 'rdfs:label "France updated"'
            ),
            encoding="utf-8",
        )
        updated_app = app_for(config, repository)
        rendered = updated_app.render(deck, stored)
        assert isinstance(rendered, Basic)
        assert str(rendered.front) == "Capital of France updated?"


def test_entity_removal_and_restoration_keeps_schedule(config: AppConfig, workspace: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-choice")
    france = CardKey.entity(URIRef("https://example.org/France"))
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, now)
        card = repository.get_card(france.digest)
        assert card is not None
        app.review(deck, card, Rating.Good, now)
        reviewed_json = repository.get_card(france.digest).card_json  # type: ignore[union-attr]

        source = workspace / "data" / "knowledge.ttl"
        original = source.read_text(encoding="utf-8")
        source.write_text(
            original.replace("ex:France ex:capital", "ex:France ex:note"),
            encoding="utf-8",
        )
        app_for(config, repository).sync(deck, now + timedelta(seconds=1))
        active = repository.connection.execute(
            "SELECT active FROM deck_cards WHERE deck_name = ? AND card_id = ?",
            (deck.name, france.digest),
        ).fetchone()[0]
        assert active == 0

        source.write_text(original, encoding="utf-8")
        app_for(config, repository).sync(deck, now + timedelta(seconds=2))
        restored = repository.get_card(france.digest)
        assert restored is not None
        assert restored.card_json == reviewed_json


def test_changing_entity_iri_creates_a_new_card(config: AppConfig, workspace: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-choice")
    with Repository(config.state_path) as repository:
        app_for(config, repository).sync(deck, now)
        original_ids = {
            row[0]
            for row in repository.connection.execute(
                "SELECT card_id FROM deck_cards WHERE deck_name = ? AND active = 1",
                (deck.name,),
            )
        }

        source = workspace / "data" / "knowledge.ttl"
        source.write_text(
            source.read_text(encoding="utf-8").replace("ex:France", "ex:FrenchRepublic"),
            encoding="utf-8",
        )
        assert app_for(config, repository).sync(deck, now + timedelta(seconds=1)) == (2, 1)
        active_ids = {
            row[0]
            for row in repository.connection.execute(
                "SELECT card_id FROM deck_cards WHERE deck_name = ? AND active = 1",
                (deck.name,),
            )
        }
        assert len(active_ids - original_ids) == 1
        assert len(original_ids - active_ids) == 1
        assert repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 3


def test_entity_render_uses_current_metadata(config: AppConfig, workspace: Path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-choice")
    france = CardKey.entity(URIRef("https://example.org/France"))
    with Repository(config.state_path) as repository:
        app_for(config, repository).sync(deck, now)
        stored = repository.get_card(france.digest)
        assert stored is not None

        source = workspace / "data" / "knowledge.ttl"
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                'rdfs:label "France"', 'rdfs:label "France updated"'
            ),
            encoding="utf-8",
        )
        rendered = app_for(config, repository).render(deck, stored)
        assert str(rendered.front) == "Capital of France updated?"


def test_naive_synchronization_time_is_rejected(config: AppConfig) -> None:
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        with pytest.raises(StorageError, match="timezone-aware"):
            app.sync(deck, datetime(2026, 1, 1))
        assert repository.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0


def test_non_utc_times_are_normalized_for_fsrs(config: AppConfig) -> None:
    local_time = datetime(2025, 12, 31, 19, tzinfo=timezone(timedelta(hours=-5)))
    expected_utc = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, local_time)
        card = repository.due_cards(deck.name, expected_utc, 1)[0]
        assert card.card().due == expected_utc

        reviewed = app.review(deck, card, Rating.Good, local_time)

        assert reviewed.card().last_review == expected_utc
        reviewed_at = repository.connection.execute(
            "SELECT reviewed_at FROM reviews WHERE card_id = ?", (card.card_id,)
        ).fetchone()[0]
        assert reviewed_at == "2026-01-01T00:00:00.000000Z"


def test_triple_and_entity_schedules_are_independent_and_ordered(
    config: AppConfig, count_reviews
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    basic = config.deck("capitals-basic")
    choice = config.deck("capitals-choice")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(basic, now)
        app.sync(choice, now)
        due_cards = repository.due_cards(basic.name, now, None)
        assert [card.card_id for card in due_cards] == sorted(card.card_id for card in due_cards)
        reviewed_id = due_cards[0].card_id
        app.review(basic, due_cards[0], Rating.Good, now)
        choice_due_ids = {card.card_id for card in repository.due_cards(choice.name, now, None)}
        assert len(choice_due_ids) == 2
        assert reviewed_id not in choice_due_ids
        assert count_reviews(repository, reviewed_id) == 1


def test_review_rejects_card_with_wrong_deck_target_without_mutation(
    config: AppConfig, count_reviews
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    triple_deck = config.deck("capitals-basic")
    entity_deck = config.deck("capitals-choice")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(triple_deck, now)
        card = repository.due_cards(triple_deck.name, now, 1)[0]
        before = repository.get_card(card.card_id)

        with pytest.raises(PresentationError, match="targets entity"):
            app.review(entity_deck, card, Rating.Good, now)

        assert repository.get_card(card.card_id) == before
        assert count_reviews(repository) == 0


@pytest.mark.parametrize("target_kind", list(TargetKind))
def test_stored_identity_hash_mismatch_is_rejected(
    config: AppConfig, target_kind: TargetKind
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck_name = "capitals-basic" if target_kind is TargetKind.TRIPLE else "capitals-choice"
    deck = config.deck(deck_name)
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, now)
        card = repository.due_cards(deck.name, now, 1)[0]
        terms = list(card.card_key.n3_terms)
        terms[-1] = "<https://example.org/tampered>"
        repository.connection.execute(
            "UPDATE cards SET identity_json = ? WHERE card_id = ?",
            (json.dumps(terms), card.card_id),
        )

        with pytest.raises(StorageError, match="identity does not match"):
            repository.get_card(card.card_id)


def test_malformed_stored_n3_is_reported_as_storage_corruption(config: AppConfig) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-choice")
    with Repository(config.state_path) as repository:
        app_for(config, repository).sync(deck, now)
        card = repository.due_cards(deck.name, now, 1)[0]
        repository.connection.execute(
            "UPDATE cards SET identity_json = ? WHERE card_id = ?",
            (json.dumps(['"value"^^bad:type']), card.card_id),
        )

        with pytest.raises(StorageError, match="invalid N3 term"):
            repository.get_card(card.card_id)


def test_card_and_log_update_roll_back_together(config: AppConfig, count_reviews) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, now)
        card = repository.due_cards(deck.name, now, 1)[0]
        repository.connection.execute(
            """
            CREATE TRIGGER fail_review BEFORE INSERT ON reviews
            BEGIN SELECT RAISE(ABORT, 'forced failure'); END
            """
        )
        before = repository.get_card(card.card_id)
        with pytest.raises(sqlite3.IntegrityError, match="forced failure"):
            app.review(deck, card, Rating.Good, now)
        after = repository.get_card(card.card_id)
        assert after == before
        assert count_reviews(repository) == 0


def test_status_counts_new_due_and_future(config: AppConfig) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, now)
        initial = repository.status(deck.name, now)
        assert (initial.active, initial.new, initial.due, initial.future) == (2, 2, 2, 0)
        app.review(deck, repository.due_cards(deck.name, now, 1)[0], Rating.Good, now)
        updated = repository.status(deck.name, now)
        assert (updated.active, updated.new, updated.due, updated.future) == (2, 1, 1, 1)


def test_fresh_database_uses_schema_v3_identity_fields(tmp_path: Path) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        version = repository.connection.execute("PRAGMA user_version").fetchone()[0]
        assert version == 3
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            repository.connection.execute(
                """
                INSERT INTO cards (
                    card_id, target_kind, identity_json, card_json, due_at, created_at, updated_at
                ) VALUES ('bad', 'unknown', '[]', '{}', 'x', 'x', 'x')
                """
            )
