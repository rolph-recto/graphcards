from __future__ import annotations

import io
from pathlib import Path

import pytest

from graphcards.cli import build_parser, main
from graphcards.config import load_config
from graphcards.storage import Repository


def run_cli(*args: str) -> tuple[int, str, str]:
    output = io.StringIO()
    error = io.StringIO()
    code = main(args, output=output, error=error)
    return code, output.getvalue(), error.getvalue()


def test_init_creates_workspace_and_refuses_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "demo"
    code, output, error = run_cli("init", str(destination))
    assert code == 0
    assert "Created empty GraphCards workspace" in output
    assert not error
    assert (destination / "graphcards.toml").is_file()
    config = load_config(destination / "graphcards.toml")
    assert config.sources == ()
    assert config.decks == ()
    assert [path.name for path in destination.iterdir()] == ["graphcards.toml"]

    code, _, error = run_cli("init", str(destination))
    assert code == 2
    assert "refusing to overwrite" in error


def test_init_creates_named_template(tmp_path: Path) -> None:
    destination = tmp_path / "demo"
    code, output, error = run_cli("init", str(destination), "--template", "capitals")

    assert code == 0
    assert "template 'capitals'" in output
    assert error == ""
    config = load_config(destination / "graphcards.toml")
    assert len(config.sources) == 1
    assert {deck.name for deck in config.decks} == {"capitals-basic", "capitals-choice"}
    assert (destination / "data" / "knowledge.ttl").is_file()
    assert (destination / "queries" / "capitals-basic.rq").is_file()
    assert (destination / "queries" / "capitals-choice.rq").is_file()


def test_init_creates_priority_capitals_example(tmp_path: Path) -> None:
    destination = tmp_path / "priority-demo"
    code, output, error = run_cli(
        "init",
        str(destination),
        "--template",
        "priority-capitals",
    )

    assert code == 0
    assert "template 'priority-capitals'" in output
    assert error == ""
    config_path = destination / "graphcards.toml"
    config = load_config(config_path)
    deck = config.deck("priority-capitals")
    assert deck.max_choices == 4
    assert (destination / "README.md").is_file()
    assert (destination / "queries" / "priority-capitals.rq").is_file()

    code, output, error = run_cli("--config", str(config_path), "validate")
    assert code == 0
    assert output == "priority-capitals: valid (2 cards)\n"
    assert error == ""


def test_init_creates_ordered_planets_example(tmp_path: Path) -> None:
    destination = tmp_path / "planets-demo"
    code, output, error = run_cli(
        "init",
        str(destination),
        "--template",
        "ordered-planets",
    )

    assert code == 0
    assert "template 'ordered-planets'" in output
    assert error == ""
    config_path = destination / "graphcards.toml"
    config = load_config(config_path)
    deck = config.deck("planet-order")
    assert deck.window_size == 5
    assert (destination / "README.md").is_file()
    assert (destination / "queries" / "planet-order.rq").is_file()

    code, output, error = run_cli("--config", str(config_path), "validate")
    assert code == 0
    assert output == "planet-order: valid (8 cards)\n"
    assert error == ""


def test_init_creates_analogy_capitals_example(tmp_path: Path) -> None:
    destination = tmp_path / "analogy-demo"
    code, output, error = run_cli(
        "init",
        str(destination),
        "--template",
        "analogy-capitals",
    )

    assert code == 0
    assert "template 'analogy-capitals'" in output
    assert error == ""
    config_path = destination / "graphcards.toml"
    config = load_config(config_path)
    config.deck("capital-analogies")
    assert (destination / "README.md").is_file()
    assert (destination / "queries" / "capital-analogies.rq").is_file()

    code, output, error = run_cli("--config", str(config_path), "validate")
    assert code == 0
    assert output == "capital-analogies: valid (6 cards)\n"
    assert error == ""


def test_init_rejects_unknown_template(tmp_path: Path) -> None:
    code, _, error = run_cli("init", str(tmp_path / "demo"), "--template", "missing")
    assert code == 2
    assert "unknown template" in error
    assert "capitals" in error


def test_templates_lists_names_without_loading_config() -> None:
    code, output, error = run_cli("--config", "missing.toml", "templates")

    assert code == 0
    assert output == "analogy-capitals\ncapitals\nordered-planets\npriority-capitals\n"
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
    assert not (destination / "graphcards.toml").exists()
    assert not (destination / "queries").exists()


def test_empty_workspace_commands_succeed(tmp_path: Path) -> None:
    destination = tmp_path / "empty"
    assert run_cli("init", str(destination))[0] == 0
    config_path = str(destination / "graphcards.toml")

    for command in ("validate", "sync", "status"):
        code, output, error = run_cli("--config", config_path, command)
        assert code == 0
        assert output == ""
        assert error == ""


def test_validate_sync_and_status(workspace: Path) -> None:
    config_path = str(workspace / "graphcards.toml")
    code, output, _ = run_cli("--config", config_path, "validate")
    assert code == 0
    assert "capitals-basic: valid (2 cards)" in output
    assert "capitals-choice: valid (2 cards)" in output

    code, output, _ = run_cli("--config", config_path, "sync")
    assert code == 0
    assert "2 current" in output

    code, output, _ = run_cli("--config", config_path, "status")
    assert code == 0
    assert "2 new, 2 due" in output


def test_full_status_shows_card_details_for_selected_deck(workspace: Path) -> None:
    config_path = str(workspace / "graphcards.toml")
    assert run_cli("--config", config_path, "sync")[0] == 0

    code, output, error = run_cli(
        "--config", config_path, "status", "--deck", "capitals-choice", "--full"
    )

    assert code == 0
    assert error == ""
    assert "capitals-choice: 2 available, 0 suspended, 2 new, 2 due, 0 future" in output
    assert "CARD ID" in output
    assert "TARGET" in output
    assert "STATUS" in output
    assert "FSRS STATE" in output
    assert "REVIEWS" in output
    assert "DUE (UTC)" in output
    assert "REASON" in output
    assert "IDENTITY" in output
    assert output.count("new/due") == 2
    assert output.count("  entity  ") == 2
    assert "capitals-basic" not in output


def test_full_status_shows_each_deck_and_handles_empty_state(workspace: Path) -> None:
    config_path = str(workspace / "graphcards.toml")

    code, output, error = run_cli("--config", config_path, "status", "--full")

    assert code == 0
    assert error == ""
    assert "capitals-basic: 0 available, 0 suspended" in output
    assert "capitals-choice: 0 available, 0 suspended" in output
    assert output.count("(no current cards)") == 2


def test_serve_dispatches_to_web_hub(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Path] = []

    def fake_server(config, **_kwargs):
        calls.append(config.state_path)

    monkeypatch.setattr("graphcards.cli.run_server", fake_server)
    code, output, error = run_cli(
        "--config",
        str(workspace / "graphcards.toml"),
        "serve",
    )

    assert code == 0
    assert calls == [workspace / ".graphcards" / "state.sqlite3"]
    assert output == ""
    assert error == ""


def test_cli_does_not_expose_terminal_study() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["study", "capitals-basic"])


def test_interrupting_serve_has_server_message(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt_server(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("graphcards.cli.run_server", interrupt_server)
    code, output, error = run_cli(
        "--config",
        str(workspace / "graphcards.toml"),
        "serve",
    )

    assert code == 130
    assert output == ""
    assert "Web server stopped." in error


def test_status_uses_persisted_state_when_source_is_unavailable(workspace: Path) -> None:
    config_path = str(workspace / "graphcards.toml")
    assert run_cli("--config", config_path, "sync")[0] == 0
    (workspace / "data" / "knowledge.ttl").unlink()
    code, output, error = run_cli("--config", config_path, "status")
    assert code == 0
    assert "2 available" in output
    assert not error


def test_cli_suspends_and_resumes_membership_without_loading_sources(
    workspace: Path,
) -> None:
    config_path = str(workspace / "graphcards.toml")
    assert run_cli("--config", config_path, "sync")[0] == 0
    config = load_config(config_path)
    with Repository(config.state_path) as repository:
        card_id = repository.active_cards("capitals-basic")[0].card_id

    (workspace / "data" / "knowledge.ttl").unlink()
    code, output, error = run_cli(
        "--config",
        config_path,
        "suspend",
        "capitals-basic",
        card_id,
        "--reason",
        "  confusing wording  ",
    )
    assert code == 0
    assert output == f"capitals-basic: suspended {card_id}\n"
    assert error == ""

    code, output, error = run_cli(
        "--config",
        config_path,
        "status",
        "--deck",
        "capitals-basic",
        "--full",
    )
    assert code == 0
    assert "1 available, 1 suspended" in output
    assert "suspended/new/due" in output
    assert "confusing wording" in output
    assert error == ""

    code, output, error = run_cli(
        "--config",
        config_path,
        "resume",
        "capitals-basic",
        card_id,
    )
    assert code == 0
    assert output == f"capitals-basic: resumed {card_id}\n"
    assert error == ""
    with Repository(config.state_path) as repository:
        assert repository.card_available("capitals-basic", card_id)


def test_cli_suspension_rejects_invalid_or_unknown_card_ids(workspace: Path) -> None:
    config_path = str(workspace / "graphcards.toml")
    with pytest.raises(SystemExit, match="2"):
        build_parser().parse_args(["suspend", "capitals-basic", "not-a-card"])

    unknown = "0" * 64
    code, _, error = run_cli(
        "--config",
        config_path,
        "resume",
        "capitals-basic",
        unknown,
    )
    assert code == 2
    assert "is not a known member" in error


@pytest.mark.parametrize(
    "reason",
    (
        "fake line\ninjection",
        "\x1b[31mred",
        "safe\u202etext",
        "zero\u200bwidth",
        "line\u2028separator",
        "surrogate\ud800",
    ),
)
def test_cli_suspension_rejects_terminal_control_characters(
    workspace: Path,
    reason: str,
) -> None:
    config_path = str(workspace / "graphcards.toml")
    assert run_cli("--config", config_path, "sync")[0] == 0
    config = load_config(config_path)
    with Repository(config.state_path) as repository:
        card_id = repository.active_cards("capitals-basic")[0].card_id

    code, _, error = run_cli(
        "--config",
        config_path,
        "suspend",
        "capitals-basic",
        card_id,
        "--reason",
        reason,
    )

    assert code == 2
    assert "cannot contain control characters" in error
    with Repository(config.state_path) as repository:
        assert repository.card_available("capitals-basic", card_id)


def test_missing_config_has_actionable_error(tmp_path: Path) -> None:
    code, _, error = run_cli("--config", str(tmp_path / "missing.toml"), "validate")
    assert code == 2
    assert "configuration file not found" in error


def test_fsrs_step_overflow_has_actionable_cli_error(workspace: Path) -> None:
    config_path = workspace / "graphcards.toml"
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
