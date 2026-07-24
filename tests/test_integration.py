from __future__ import annotations

import json
import random
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fsrs import Card, Rating
from rdflib import URIRef

from rdfcards.app import StudyService
from rdfcards.config import AppConfig, load_config
from rdfcards.decks import BasicPresentation, MultipleChoicePresentation
from rdfcards.errors import PresentationError, StorageError
from rdfcards.models import CardKey, TargetKind
from rdfcards.presentation import execute_presentations, load_graph
from rdfcards.scaffold import initialize_workspace
from rdfcards.storage import Repository, datetime_to_text


def app_for(config: AppConfig, repository: Repository) -> StudyService:
    return StudyService(load_graph(config.sources), repository, config.fsrs.create_scheduler())


def set_card_due(repository: Repository, card_id: str, due: datetime) -> None:
    stored = repository.get_card(card_id)
    assert stored is not None
    card = stored.card()
    card.due = due
    repository.connection.execute(
        "UPDATE cards SET card_json = ?, due_at = ? WHERE card_id = ?",
        (card.to_json(), datetime_to_text(due), card_id),
    )


def test_priority_capitals_template_exhausts_tiers_and_keeps_correct_answer(
    tmp_path: Path,
) -> None:
    initialize_workspace(tmp_path, template="priority-capitals")
    config = load_config(tmp_path / "rdfcards.toml")
    deck = config.deck("priority-capitals")
    presentations = execute_presentations(load_graph(config.sources), deck)
    by_front = {str(presentation.front): presentation for presentation in presentations.values()}

    france = by_front["Capital of France?"]
    assert isinstance(france, MultipleChoicePresentation)
    assert {str(option.choice): option.priority for option in france.choices} == {
        "Paris": 0,
        "Berlin": 3,
        "Rome": 2,
        "Madrid": 1,
        "Lisbon": 1,
    }
    rng = random.Random(0)
    france_renders = tuple(
        {str(choice) for choice in france.selected_choices(rng)} for _ in range(8)
    )
    assert all({"Paris", "Berlin", "Rome"} <= selected for selected in france_renders)
    assert all(len(selected & {"Madrid", "Lisbon"}) == 1 for selected in france_renders)
    assert {next(iter(selected & {"Madrid", "Lisbon"})) for selected in france_renders} == {
        "Madrid",
        "Lisbon",
    }

    germany = by_front["Capital of Germany?"]
    assert isinstance(germany, MultipleChoicePresentation)
    selected = {str(choice) for choice in germany.selected_choices(random.Random(0))}
    assert {"Berlin", "Paris", "Rome"} <= selected
    assert len(selected & {"Madrid", "Lisbon"}) == 1


def test_sync_is_idempotent_and_entities_are_shared_across_decks(config: AppConfig) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        basic = config.deck("capitals-basic")
        basic_copy = basic.model_copy(update={"name": "capitals-basic-copy"})
        assert app.sync(basic, now) == (2, 2)
        assert app.sync(basic, now) == (2, 0)
        assert app.sync(basic_copy, now) == (2, 0)
        choice = config.deck("capitals-choice")
        choice_copy = choice.model_copy(update={"name": "capitals-choice-copy"})
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


def test_advanced_card_selectors_use_global_history_and_schedule_windows(
    config: AppConfig,
) -> None:
    now = datetime(2026, 1, 3, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    deck_copy = deck.model_copy(update={"name": "capitals-basic-copy"})
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, now)
        app.sync(deck_copy, now)
        older, recent = repository.due_cards(deck.name, now, None)
        app.review(deck, older, Rating.Again, now - timedelta(days=2))
        app.review(deck, recent, Rating.Again, now)

        forgotten = repository.forgotten_cards(
            deck_copy.name,
            now - timedelta(days=1),
            None,
        )
        assert [card.card_id for card in forgotten] == [recent.card_id]
        assert {card.card_id for card in repository.active_cards(deck_copy.name)} == {
            older.card_id,
            recent.card_id,
        }

        set_card_due(repository, recent.card_id, now + timedelta(hours=12))
        set_card_due(repository, older.card_id, now + timedelta(days=2))
        ahead = repository.future_cards(
            deck_copy.name,
            now,
            now + timedelta(days=1),
            1,
        )
        assert [card.card_id for card in ahead] == [recent.card_id]


def test_due_mirror_mismatch_is_detected_before_indexed_filters_can_omit_it(
    config: AppConfig,
) -> None:
    now = datetime(2026, 1, 3, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app_for(config, repository).sync(deck, now)
        card = repository.due_cards(deck.name, now, 1)[0]
        repository.connection.execute(
            "UPDATE cards SET due_at = ? WHERE card_id = ?",
            (datetime_to_text(now + timedelta(days=1)), card.card_id),
        )

        with pytest.raises(StorageError, match="due timestamp does not match"):
            repository.due_cards(deck.name, now, None)
        with pytest.raises(StorageError, match="due timestamp does not match"):
            repository.future_cards(deck.name, now, now + timedelta(days=2), None)
        with pytest.raises(StorageError, match="due timestamp does not match"):
            repository.status(deck.name, now)
        with pytest.raises(StorageError, match="due timestamp does not match"):
            repository.active_cards(deck.name)
        with pytest.raises(StorageError, match="due timestamp does not match"):
            repository.get_card(card.card_id)
        with pytest.raises(StorageError, match="due timestamp does not match"):
            repository.card_statuses(deck.name)


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


def test_suspension_survives_sync_and_excludes_every_queue(config: AppConfig) -> None:
    now = datetime(2026, 1, 3, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        presentations = app.render_all(deck)
        app.sync(deck, now)
        card = repository.due_cards(deck.name, now, 1)[0]
        reviewed = app.review(deck, card, Rating.Again, now)
        set_card_due(repository, card.card_id, now + timedelta(hours=12))
        before = repository.get_card(card.card_id)
        assert before is not None
        review_count = repository.connection.execute(
            "SELECT COUNT(*) FROM reviews WHERE card_id = ?", (card.card_id,)
        ).fetchone()[0]

        repository.suspend_card(deck.name, card.card_id, "  needs a better prompt  ")

        assert card.card_id not in {row.card_id for row in repository.active_cards(deck.name)}
        assert card.card_id not in {
            row.card_id for row in repository.due_cards(deck.name, now, None)
        }
        assert card.card_id not in {
            row.card_id
            for row in repository.forgotten_cards(
                deck.name,
                now - timedelta(days=1),
                None,
            )
        }
        assert card.card_id not in {
            row.card_id
            for row in repository.future_cards(
                deck.name,
                now,
                now + timedelta(days=1),
                None,
            )
        }
        status = repository.status(deck.name, now)
        assert (status.available, status.suspended) == (1, 1)
        suspended = next(
            row for row in repository.card_statuses(deck.name) if row.card_id == card.card_id
        )
        assert suspended.suspended
        assert suspended.suspension_reason == "needs a better prompt"

        repository.sync_deck(deck.name, {}, now + timedelta(seconds=1))
        repository.sync_deck(deck.name, presentations, now + timedelta(seconds=2))
        restored = next(
            row for row in repository.card_statuses(deck.name) if row.card_id == card.card_id
        )
        assert restored.suspended
        assert restored.suspension_reason == "needs a better prompt"

        repository.resume_card(deck.name, card.card_id)

        assert card.card_id in {row.card_id for row in repository.active_cards(deck.name)}
        assert card.card_id in {
            row.card_id
            for row in repository.forgotten_cards(
                deck.name,
                now - timedelta(days=1),
                None,
            )
        }
        assert card.card_id in {
            row.card_id
            for row in repository.future_cards(
                deck.name,
                now,
                now + timedelta(days=1),
                None,
            )
        }
        resumed = repository.get_card(card.card_id)
        assert resumed is not None
        assert resumed.card_json == before.card_json
        assert reviewed.card_id == resumed.card_id
        assert (
            repository.connection.execute(
                "SELECT COUNT(*) FROM reviews WHERE card_id = ?", (card.card_id,)
            ).fetchone()[0]
            == review_count
        )


def test_suspension_is_per_membership_while_schedule_remains_global(
    config: AppConfig,
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    shared = deck.model_copy(update={"name": "capitals-shared"})
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, now)
        app.sync(shared, now)
        card = repository.due_cards(deck.name, now, 1)[0]

        repository.suspend_card(deck.name, card.card_id, None)

        assert card.card_id not in {
            row.card_id for row in repository.due_cards(deck.name, now, None)
        }
        shared_card = next(
            row
            for row in repository.due_cards(shared.name, now, None)
            if row.card_id == card.card_id
        )
        updated = app.review(shared, shared_card, Rating.Good, now)
        repository.resume_card(deck.name, card.card_id)

        resumed = repository.get_card(card.card_id)
        assert resumed is not None
        assert resumed.card_json == updated.card_json
        assert card.card_id not in {
            row.card_id for row in repository.due_cards(deck.name, now, None)
        }


def test_suspended_snapshot_cannot_record_a_review(config: AppConfig) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, now)
        card = repository.due_cards(deck.name, now, 1)[0]
        before = repository.get_card(card.card_id)
        repository.suspend_card(deck.name, card.card_id, None)

        with pytest.raises(StorageError, match="cannot review unavailable card"):
            app.review(deck, card, Rating.Good, now)

        assert repository.get_card(card.card_id) == before
        assert repository.connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0


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
        assert isinstance(rendered, BasicPresentation)
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


def test_non_text_card_schedule_is_reported_as_storage_corruption(
    config: AppConfig,
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app_for(config, repository).sync(deck, now)
        card = repository.due_cards(deck.name, now, 1)[0]
        repository.connection.execute(
            "UPDATE cards SET card_json = ? WHERE card_id = ?",
            (sqlite3.Binary(b"{}"), card.card_id),
        )

        with pytest.raises(StorageError, match="schedule is not JSON text"):
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


def test_review_rejects_stale_card_snapshot_without_mutation(
    config: AppConfig, count_reviews
) -> None:
    first_review = datetime(2026, 1, 1, tzinfo=UTC)
    stale_review = first_review + timedelta(minutes=1)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, first_review)
        first_snapshot = repository.due_cards(deck.name, first_review, 1)[0]
        stale_snapshot = repository.get_card(first_snapshot.card_id)
        assert stale_snapshot == first_snapshot

        app.review(deck, first_snapshot, Rating.Good, first_review)
        current = repository.get_card(first_snapshot.card_id)
        history = repository.review_history(deck.name, stale_review)

        with pytest.raises(StorageError, match="stale card snapshot"):
            app.review(deck, stale_snapshot, Rating.Again, stale_review)

        assert repository.get_card(first_snapshot.card_id) == current
        assert repository.review_history(deck.name, stale_review) == history
        assert count_reviews(repository, first_snapshot.card_id) == 1


def test_status_counts_new_due_and_future(config: AppConfig) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, now)
        initial = repository.status(deck.name, now)
        assert (
            initial.available,
            initial.suspended,
            initial.new,
            initial.due,
            initial.future,
        ) == (2, 0, 2, 2, 0)
        app.review(deck, repository.due_cards(deck.name, now, 1)[0], Rating.Good, now)
        updated = repository.status(deck.name, now)
        assert (
            updated.available,
            updated.suspended,
            updated.new,
            updated.due,
            updated.future,
        ) == (2, 0, 1, 1, 1)


def test_card_statuses_include_latest_global_review_and_fsrs_metrics(
    config: AppConfig,
) -> None:
    first_review = datetime(2026, 1, 1, tzinfo=UTC)
    latest_review = first_review + timedelta(minutes=2)
    deck = config.deck("capitals-basic")
    shared_deck = deck.model_copy(update={"name": "capitals-status-copy"})
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, first_review)
        app.sync(shared_deck, first_review)
        card = repository.due_cards(deck.name, first_review, 1)[0]
        reviewed = app.review(deck, card, Rating.Again, first_review)
        reviewed = app.review(deck, reviewed, Rating.Good, latest_review)

        status = next(
            row for row in repository.card_statuses(shared_deck.name) if row.card_id == card.card_id
        )

        assert status.review_count == 2
        assert status.last_review_at == latest_review
        assert status.last_rating is Rating.Good
        assert status.fsrs_state == reviewed.card().state.name.lower()
        assert status.fsrs_step == reviewed.card().step
        assert status.stability == reviewed.card().stability
        assert status.difficulty == reviewed.card().difficulty
        assert status.due_at == reviewed.card().due
        assert status.stored_card() == reviewed


def test_review_history_uses_event_deck_and_validates_immutable_metrics(
    config: AppConfig,
) -> None:
    first_review = datetime(2026, 1, 1, tzinfo=UTC)
    second_review = first_review + timedelta(days=1)
    deck = config.deck("capitals-basic")
    shared_deck = deck.model_copy(update={"name": "capitals-history-copy"})
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, first_review)
        app.sync(shared_deck, first_review)
        card = repository.due_cards(deck.name, first_review, 1)[0]
        reviewed = app.review(deck, card, Rating.Good, first_review)
        app.review(deck, reviewed, Rating.Hard, second_review)

        records = repository.review_history(deck.name, second_review)

        assert len(records) == 2
        assert records[0].previous_interval_seconds is None
        assert records[0].scheduled_interval_seconds is not None
        assert records[0].retrievability is None
        assert records[1].previous_interval_seconds == records[0].scheduled_interval_seconds
        assert records[1].scheduled_interval_seconds is not None
        assert records[1].retrievability is not None
        assert repository.review_history(shared_deck.name, second_review) == ()

        repository.connection.execute(
            "UPDATE reviews SET review_json = ? WHERE id = ?",
            ("not JSON", records[0].review_id),
        )
        with pytest.raises(StorageError, match="review log is invalid"):
            repository.review_history(deck.name, second_review)


def test_fresh_database_uses_schema_v4_suspension_fields(tmp_path: Path) -> None:
    with Repository(tmp_path / "state.sqlite3") as repository:
        version = repository.connection.execute("PRAGMA user_version").fetchone()[0]
        assert version == 4
        columns = {
            row["name"] for row in repository.connection.execute("PRAGMA table_info(deck_cards)")
        }
        assert {"suspended", "suspension_reason"} <= columns
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            repository.connection.execute(
                """
                INSERT INTO cards (
                    card_id, target_kind, identity_json, card_json, due_at, created_at, updated_at
                ) VALUES ('bad', 'unknown', '[]', '{}', 'x', 'x', 'x')
                """
            )


def test_schema_v3_migration_preserves_schedules_reviews_and_memberships(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    card_key = CardKey.triple(
        URIRef("https://example.org/subject"),
        URIRef("https://example.org/predicate"),
        URIRef("https://example.org/object"),
    )
    card_json = Card(due=now).to_json()
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE cards (
            card_id TEXT PRIMARY KEY,
            target_kind TEXT NOT NULL CHECK (target_kind IN ('triple', 'entity')),
            identity_json TEXT NOT NULL,
            card_json TEXT NOT NULL,
            due_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE deck_cards (
            deck_name TEXT NOT NULL,
            card_id TEXT NOT NULL REFERENCES cards(card_id),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (deck_name, card_id)
        );
        CREATE TABLE reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL REFERENCES cards(card_id),
            deck_name TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
            reviewed_at TEXT NOT NULL,
            review_json TEXT NOT NULL
        );
        PRAGMA user_version = 3;
        """
    )
    timestamp = datetime_to_text(now)
    connection.execute(
        """
        INSERT INTO cards (
            card_id, target_kind, identity_json, card_json, due_at, created_at, updated_at
        ) VALUES (?, 'triple', ?, ?, ?, ?, ?)
        """,
        (
            card_key.digest,
            json.dumps(card_key.n3_terms),
            card_json,
            timestamp,
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        "INSERT INTO deck_cards VALUES ('deck', ?, 1, ?)",
        (card_key.digest, timestamp),
    )
    connection.execute(
        "INSERT INTO reviews (card_id, deck_name, rating, reviewed_at, review_json) "
        "VALUES (?, 'deck', 3, ?, 'preserved review')",
        (card_key.digest, timestamp),
    )
    connection.commit()
    connection.close()

    with Repository(path) as repository:
        assert repository.connection.execute("PRAGMA user_version").fetchone()[0] == 4
        membership = repository.connection.execute(
            """
            SELECT active, suspended, suspension_reason
            FROM deck_cards WHERE deck_name = 'deck' AND card_id = ?
            """,
            (card_key.digest,),
        ).fetchone()
        assert tuple(membership) == (1, 0, None)
        assert (
            repository.connection.execute(
                "SELECT card_json FROM cards WHERE card_id = ?", (card_key.digest,)
            ).fetchone()[0]
            == card_json
        )
        assert (
            repository.connection.execute(
                "SELECT review_json FROM reviews WHERE card_id = ?", (card_key.digest,)
            ).fetchone()[0]
            == "preserved review"
        )


def test_schema_v3_migration_rolls_back_on_schema_drift(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE deck_cards (
            deck_name TEXT NOT NULL,
            card_id TEXT NOT NULL,
            active INTEGER NOT NULL,
            suspension_reason TEXT,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (deck_name, card_id)
        );
        PRAGMA user_version = 3;
        """
    )
    connection.close()

    with pytest.raises(StorageError, match="could not migrate state schema"):
        Repository(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {row[1] for row in connection.execute("PRAGMA table_info(deck_cards)").fetchall()}
        assert "suspension_reason" in columns
        assert "suspended" not in columns
    finally:
        connection.close()


def test_schema_v3_migration_rolls_back_on_late_index_failure(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE deck_cards (
            deck_name TEXT NOT NULL,
            card_id TEXT NOT NULL,
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (deck_name, card_id)
        );
        PRAGMA user_version = 3;
        """
    )
    connection.close()

    with pytest.raises(StorageError, match="could not migrate state schema"):
        Repository(path)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {row[1] for row in connection.execute("PRAGMA table_info(deck_cards)").fetchall()}
        assert "suspended" not in columns
        assert "suspension_reason" not in columns
    finally:
        connection.close()


def test_queue_and_status_selectors_reject_corrupt_suspension_state(
    config: AppConfig,
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app = app_for(config, repository)
        app.sync(deck, now)
        card = repository.active_cards(deck.name)[0]

        selectors = (
            lambda: repository.active_cards(deck.name),
            lambda: repository.due_cards(deck.name, now, None),
            lambda: repository.forgotten_cards(deck.name, now - timedelta(days=1), None),
            lambda: repository.future_cards(deck.name, now, now + timedelta(days=1), None),
            lambda: repository.status(deck.name, now),
            lambda: repository.card_statuses(deck.name),
        )

        repository.connection.execute(
            """
            UPDATE deck_cards
            SET suspended = 0, suspension_reason = 'orphaned reason'
            WHERE deck_name = ? AND card_id = ?
            """,
            (deck.name, card.card_id),
        )
        repository.connection.commit()
        for select in selectors:
            with pytest.raises(
                StorageError,
                match="stored resumed deck membership still has a suspension reason",
            ):
                select()
        with pytest.raises(
            StorageError,
            match="stored resumed deck membership still has a suspension reason",
        ):
            app.review(deck, card, Rating.Good, now)

        repository.connection.execute("PRAGMA ignore_check_constraints = ON")
        repository.connection.execute(
            """
            UPDATE deck_cards
            SET suspended = 2, suspension_reason = NULL
            WHERE deck_name = ? AND card_id = ?
            """,
            (deck.name, card.card_id),
        )
        repository.connection.commit()
        repository.connection.execute("PRAGMA ignore_check_constraints = OFF")
        for select in selectors:
            with pytest.raises(
                StorageError,
                match="stored deck membership has an invalid suspension state",
            ):
                select()
        with pytest.raises(
            StorageError,
            match="stored deck membership has an invalid suspension state",
        ):
            app.review(deck, card, Rating.Good, now)

        repository.connection.execute(
            """
            UPDATE deck_cards
            SET suspended = 1, suspension_reason = ?
            WHERE deck_name = ? AND card_id = ?
            """,
            ("safe\u202etext", deck.name, card.card_id),
        )
        repository.connection.commit()
        for select in selectors:
            with pytest.raises(
                StorageError,
                match="stored deck membership has an invalid suspension reason",
            ):
                select()
        with pytest.raises(
            StorageError,
            match="stored deck membership has an invalid suspension reason",
        ):
            app.review(deck, card, Rating.Good, now)
        assert repository.connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0


def test_suspension_reason_validation_is_user_facing(config: AppConfig) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    deck = config.deck("capitals-basic")
    with Repository(config.state_path) as repository:
        app_for(config, repository).sync(deck, now)
        card = repository.active_cards(deck.name)[0]

        with pytest.raises(StorageError, match="at most 500 characters"):
            repository.suspend_card(deck.name, card.card_id, "x" * 501)

        assert repository.card_available(deck.name, card.card_id)
