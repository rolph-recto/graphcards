from __future__ import annotations

import io
import random
from pathlib import Path
from typing import ClassVar

import pytest
from fsrs import Rating
from rdflib import Literal, URIRef

from rdfcards.cli import _rate_presentation, _run_study, main
from rdfcards.config import AppConfig, DeckDefinition, load_config
from rdfcards.decks import Basic, DeckKind, MultipleChoice
from rdfcards.models import CardKey
from rdfcards.storage import Repository


class NoShuffleRandom(random.Random):
    def shuffle(self, choices: list[object]) -> None:
        del choices


def inputs(*values: str):
    iterator = iter(values)
    return lambda: next(iterator)


def run_cli(*args: str, input_fn=None, rng=None) -> tuple[int, str, str]:
    output = io.StringIO()
    error = io.StringIO()
    code = main(args, input_fn=input_fn or inputs(), output=output, error=error, rng=rng)
    return code, output.getvalue(), error.getvalue()


def presentation(kind: type[DeckKind]) -> DeckKind:
    key = CardKey.triple(
        URIRef("https://example.org/subject"),
        URIRef("https://example.org/predicate"),
        URIRef("https://example.org/object"),
    )
    if kind is MultipleChoice:
        return MultipleChoice(
            card_key=key,
            front=Literal("question"),
            back=Literal("correct"),
            choices=(Literal("correct"), Literal("incorrect")),
        )
    return Basic(card_key=key, front=Literal("front"), back=Literal("back"))


@pytest.mark.parametrize("kind", [Basic, MultipleChoice])
@pytest.mark.parametrize(
    ("answer", "rating"),
    [
        ("1", Rating.Again),
        ("2", Rating.Hard),
        ("3", Rating.Good),
        ("4", Rating.Easy),
    ],
)
def test_shared_interaction_maps_every_rating(
    kind: type[DeckKind], answer: str, rating: Rating
) -> None:
    result = _rate_presentation(
        presentation(kind), inputs("", answer), io.StringIO(), NoShuffleRandom()
    )

    assert result is rating


@pytest.mark.parametrize("kind", [Basic, MultipleChoice])
def test_shared_interaction_hides_back_until_reveal(kind: type[DeckKind]) -> None:
    output = io.StringIO()
    snapshots: list[str] = []
    answers = iter(("", "3"))

    def staged_input() -> str:
        snapshots.append(output.getvalue())
        return next(answers)

    result = _rate_presentation(presentation(kind), staged_input, output, NoShuffleRandom())

    assert result is Rating.Good
    assert "Front:" in snapshots[0]
    assert "Back:" not in snapshots[0]
    assert "Back:" in snapshots[1]
    if kind is MultipleChoice:
        assert "1. correct" in snapshots[0]
        assert "2. incorrect" in snapshots[0]


@pytest.mark.parametrize("kind", [Basic, MultipleChoice])
def test_shared_interaction_retries_invalid_reveal_and_rating(kind: type[DeckKind]) -> None:
    output = io.StringIO()

    result = _rate_presentation(
        presentation(kind),
        inputs("not enter", "", "invalid", "2"),
        output,
        NoShuffleRandom(),
    )

    assert result is Rating.Hard
    assert "Please press Enter to reveal, or q to quit." in output.getvalue()
    assert "Please enter 1, 2, 3, 4, or q." in output.getvalue()


@pytest.mark.parametrize("kind", [Basic, MultipleChoice])
@pytest.mark.parametrize("answers", [("q",), ("", "q")])
def test_shared_interaction_can_quit_without_a_rating(
    kind: type[DeckKind], answers: tuple[str, ...]
) -> None:
    assert (
        _rate_presentation(presentation(kind), inputs(*answers), io.StringIO(), NoShuffleRandom())
        is None
    )


def test_init_creates_workspace_and_refuses_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "demo"
    code, output, error = run_cli("init", str(destination))
    assert code == 0
    assert "Created empty RDFCards workspace" in output
    assert not error
    assert (destination / "rdfcards.toml").is_file()
    config = load_config(destination / "rdfcards.toml")
    assert config.sources == ()
    assert config.decks == ()
    assert [path.name for path in destination.iterdir()] == ["rdfcards.toml"]

    code, _, error = run_cli("init", str(destination))
    assert code == 2
    assert "refusing to overwrite" in error


def test_init_creates_named_template(tmp_path: Path) -> None:
    destination = tmp_path / "demo"
    code, output, error = run_cli("init", str(destination), "--template", "capitals")

    assert code == 0
    assert "template 'capitals'" in output
    assert error == ""
    config = load_config(destination / "rdfcards.toml")
    assert len(config.sources) == 1
    assert {deck.name for deck in config.decks} == {"capitals-basic", "capitals-choice"}
    assert (destination / "data" / "knowledge.ttl").is_file()
    assert (destination / "queries" / "capitals-basic.rq").is_file()
    assert (destination / "queries" / "capitals-choice.rq").is_file()


def test_init_rejects_unknown_template(tmp_path: Path) -> None:
    code, _, error = run_cli("init", str(tmp_path / "demo"), "--template", "missing")
    assert code == 2
    assert "unknown template" in error
    assert "capitals" in error


def test_templates_lists_names_without_loading_config() -> None:
    code, output, error = run_cli("--config", "missing.toml", "templates")

    assert code == 0
    assert output == "capitals\n"
    assert error == ""


def test_template_init_checks_all_destinations_before_writing(tmp_path: Path) -> None:
    destination = tmp_path / "demo"
    existing = destination / "data" / "knowledge.ttl"
    existing.parent.mkdir(parents=True)
    existing.write_text("keep", encoding="utf-8")

    code, _, error = run_cli("init", str(destination), "--template", "capitals")

    assert code == 2
    assert "refusing to overwrite" in error
    assert existing.read_text(encoding="utf-8") == "keep"
    assert not (destination / "rdfcards.toml").exists()
    assert not (destination / "queries").exists()


def test_empty_workspace_commands_succeed(tmp_path: Path) -> None:
    destination = tmp_path / "empty"
    assert run_cli("init", str(destination))[0] == 0
    config_path = str(destination / "rdfcards.toml")

    for command in ("validate", "sync", "status"):
        code, output, error = run_cli("--config", config_path, command)
        assert code == 0
        assert output == ""
        assert error == ""


def test_validate_sync_and_status(workspace: Path) -> None:
    config_path = str(workspace / "rdfcards.toml")
    code, output, _ = run_cli("--config", config_path, "validate")
    assert code == 0
    assert "capitals-basic: valid (2 cards)" in output
    assert "capitals-choice: valid (2 cards)" in output

    code, output, _ = run_cli("--config", config_path, "sync")
    assert code == 0
    assert "2 active" in output

    code, output, _ = run_cli("--config", config_path, "status")
    assert code == 0
    assert "2 new, 2 due" in output


def test_full_status_shows_card_details_for_selected_deck(workspace: Path) -> None:
    config_path = str(workspace / "rdfcards.toml")
    assert run_cli("--config", config_path, "sync")[0] == 0

    code, output, error = run_cli(
        "--config", config_path, "status", "--deck", "capitals-choice", "--full"
    )

    assert code == 0
    assert error == ""
    assert "capitals-choice: 2 active, 2 new, 2 due, 0 future" in output
    assert "CARD ID" in output
    assert "TARGET" in output
    assert "STATUS" in output
    assert "FSRS STATE" in output
    assert "REVIEWS" in output
    assert "DUE (UTC)" in output
    assert "IDENTITY" in output
    assert output.count("new/due") == 2
    assert output.count("  entity  ") == 2
    assert "capitals-basic" not in output


def test_full_status_shows_each_deck_and_handles_empty_state(workspace: Path) -> None:
    config_path = str(workspace / "rdfcards.toml")

    code, output, error = run_cli("--config", config_path, "status", "--full")

    assert code == 0
    assert error == ""
    assert "capitals-basic: 0 active" in output
    assert "capitals-choice: 0 active" in output
    assert output.count("(no active cards)") == 2


def test_full_status_reflects_a_persisted_review(workspace: Path) -> None:
    config_path = str(workspace / "rdfcards.toml")
    code, _, _ = run_cli(
        "--config",
        config_path,
        "study",
        "capitals-choice",
        "--limit",
        "1",
        input_fn=inputs("", "3"),
        rng=NoShuffleRandom(),
    )
    assert code == 0

    code, output, error = run_cli(
        "--config", config_path, "status", "--deck", "capitals-choice", "--full"
    )

    assert code == 0
    assert error == ""
    assert "1 new, 1 due, 1 future" in output
    assert output.count("new/due") == 1
    assert "future" in output
    assert "  1        " in output


def test_study_uses_custom_deck_kind_front_text(config: AppConfig) -> None:
    class CustomKind(DeckKind):
        config_name = "custom_cli"
        required_variables = Basic.required_variables
        rendered: ClassVar[bool] = False

        @classmethod
        def group(cls, *args, **kwargs):
            presentations = Basic.group(*args, **kwargs)
            return {
                card_id: cls(
                    card_key=presentation.card_key,
                    front=presentation.front,
                    back=presentation.back,
                )
                for card_id, presentation in presentations.items()
            }

        def front_text(self, rng: random.Random) -> str:
            type(self).rendered = True
            return super().front_text(rng)

    source_deck = config.deck("capitals-basic")
    deck = DeckDefinition(
        name="custom",
        target=source_deck.target,
        kind=CustomKind,
        query_path=source_deck.query_path,
    )
    custom_config = config.model_copy(update={"decks": (deck,)})
    output = io.StringIO()

    _run_study(
        custom_config,
        deck.name,
        1,
        input_fn=inputs("q"),
        output=output,
        error=io.StringIO(),
        rng=random.Random(0),
    )

    assert CustomKind.rendered
    assert "Stopped. Reviewed 0 card(s)." in output.getvalue()


def test_basic_study_records_rating(workspace: Path, count_reviews) -> None:
    config_path = str(workspace / "rdfcards.toml")
    code, output, error = run_cli(
        "--config",
        config_path,
        "study",
        "capitals-basic",
        "--limit",
        "1",
        input_fn=inputs("", "3"),
    )
    assert code == 0
    assert "Front:" in output and "Back:" in output
    assert "Reviewed 1 card(s)." in output
    assert not error
    config = load_config(config_path)
    with Repository(config.state_path) as repository:
        assert count_reviews(repository) == 1


def test_multiple_choice_study_records_manual_rating(workspace: Path) -> None:
    config_path = str(workspace / "rdfcards.toml")
    code, output, error = run_cli(
        "--config",
        config_path,
        "study",
        "capitals-choice",
        "--limit",
        "1",
        input_fn=inputs("", "4"),
        rng=NoShuffleRandom(),
    )
    assert code == 0
    assert "Front:" in output
    assert "  1." in output
    assert "Back:" in output
    assert "Reviewed 1 card(s)." in output
    assert "Correct." not in output
    assert "Incorrect." not in output
    assert not error
    config = load_config(config_path)
    with Repository(config.state_path) as repository:
        rating = repository.connection.execute("SELECT rating FROM reviews").fetchone()[0]
        assert rating == 4


@pytest.mark.parametrize("answers", [("q",), ("", "q")])
def test_quit_does_not_review_current_card(
    workspace: Path, count_reviews, answers: tuple[str, ...]
) -> None:
    config_path = str(workspace / "rdfcards.toml")
    code, output, _ = run_cli(
        "--config",
        config_path,
        "study",
        "capitals-basic",
        input_fn=inputs(*answers),
    )
    assert code == 0
    assert "Reviewed 0 card(s)" in output
    config = load_config(config_path)
    with Repository(config.state_path) as repository:
        assert count_reviews(repository) == 0


@pytest.mark.parametrize("answers", [("q",), ("", "q")])
def test_multiple_choice_quit_does_not_review_current_card(
    workspace: Path, count_reviews, answers: tuple[str, ...]
) -> None:
    config_path = str(workspace / "rdfcards.toml")
    code, output, _ = run_cli(
        "--config",
        config_path,
        "study",
        "capitals-choice",
        input_fn=inputs(*answers),
    )
    assert code == 0
    assert "Reviewed 0 card(s)" in output
    config = load_config(config_path)
    with Repository(config.state_path) as repository:
        assert count_reviews(repository) == 0


@pytest.mark.parametrize("answers_before_interrupt", [(), ("",)])
def test_interrupt_does_not_review_current_card(
    workspace: Path,
    count_reviews,
    answers_before_interrupt: tuple[str, ...],
) -> None:
    answers = iter(answers_before_interrupt)

    def interrupt() -> str:
        try:
            return next(answers)
        except StopIteration:
            raise KeyboardInterrupt from None

    config_path = str(workspace / "rdfcards.toml")
    code, _, error = run_cli(
        "--config",
        config_path,
        "study",
        "capitals-basic",
        input_fn=interrupt,
    )
    assert code == 130
    assert "current card was not reviewed" in error
    config = load_config(config_path)
    with Repository(config.state_path) as repository:
        assert count_reviews(repository) == 0


@pytest.mark.parametrize("answers_before_eof", [(), ("",)])
def test_end_of_input_does_not_review_current_card(
    workspace: Path,
    count_reviews,
    answers_before_eof: tuple[str, ...],
) -> None:
    answers = iter(answers_before_eof)

    def end_input() -> str:
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    config_path = str(workspace / "rdfcards.toml")
    code, _, error = run_cli(
        "--config",
        config_path,
        "study",
        "capitals-basic",
        input_fn=end_input,
    )
    assert code == 130
    assert "current card was not reviewed" in error
    config = load_config(config_path)
    with Repository(config.state_path) as repository:
        assert count_reviews(repository) == 0


def test_empty_due_queue(workspace: Path) -> None:
    config_path = str(workspace / "rdfcards.toml")
    code, _, _ = run_cli(
        "--config",
        config_path,
        "study",
        "capitals-basic",
        input_fn=inputs("", "3", "", "3"),
    )
    assert code == 0
    code, output, error = run_cli(
        "--config", config_path, "study", "capitals-basic", input_fn=inputs()
    )
    assert code == 0
    assert output == "No cards are due.\n"
    assert not error


def test_status_uses_persisted_state_when_source_is_unavailable(workspace: Path) -> None:
    config_path = str(workspace / "rdfcards.toml")
    assert run_cli("--config", config_path, "sync")[0] == 0
    (workspace / "data" / "knowledge.ttl").unlink()
    code, output, error = run_cli("--config", config_path, "status")
    assert code == 0
    assert "2 active" in output
    assert not error


def test_missing_config_has_actionable_error(tmp_path: Path) -> None:
    code, _, error = run_cli("--config", str(tmp_path / "missing.toml"), "validate")
    assert code == 2
    assert "configuration file not found" in error


def test_fsrs_step_overflow_has_actionable_cli_error(workspace: Path) -> None:
    config_path = workspace / "rdfcards.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "learning_steps_minutes = [1, 10]",
            "learning_steps_minutes = [1000000000000000000]",
        ),
        encoding="utf-8",
    )

    code, _, error = run_cli("--config", str(config_path), "validate")

    assert code == 2
    assert "invalid FSRS settings" in error
