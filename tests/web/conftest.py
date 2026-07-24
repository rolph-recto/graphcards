from __future__ import annotations

import pytest

from graphcards.config import AppConfig
from tests.web.support import make_test_hub


@pytest.fixture
def hub_server(config: AppConfig):
    server = make_test_hub(config)
    try:
        yield server
    finally:
        server.close()
