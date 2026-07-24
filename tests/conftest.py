from __future__ import annotations

from pathlib import Path

import pytest

from graphcards.config import AppConfig, load_config
from graphcards.scaffold import initialize_workspace
from graphcards.storage import Repository


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    initialize_workspace(tmp_path, template="capitals")
    return tmp_path


@pytest.fixture
def config(workspace: Path) -> AppConfig:
    return load_config(workspace / "graphcards.toml")


@pytest.fixture
def count_reviews():
    def count(repository: Repository, card_id: str | None = None) -> int:
        if card_id is None:
            row = repository.connection.execute("SELECT COUNT(*) FROM reviews").fetchone()
        else:
            row = repository.connection.execute(
                "SELECT COUNT(*) FROM reviews WHERE card_id = ?", (card_id,)
            ).fetchone()
        return row[0]

    return count
