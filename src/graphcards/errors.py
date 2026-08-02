class GraphCardsError(Exception):
    """Base class for errors that should be shown directly to CLI users."""


class ConfigError(GraphCardsError):
    """The project configuration is invalid."""


class PresentationError(GraphCardsError):
    """A generated exercise or its presentation is invalid."""


class StorageError(GraphCardsError):
    """Persistent state is inconsistent or cannot be updated safely."""


class StaleReviewError(StorageError):
    """A review was based on a card schedule that is no longer current."""


class DailyLimitError(StorageError):
    """A saved review would exceed one of the configured daily budgets."""

    def __init__(self, budget: str, remaining: int) -> None:
        if budget not in {"new", "reviews"}:
            raise ValueError(f"unknown daily budget {budget!r}")
        if type(remaining) is not int or remaining < 0:
            raise ValueError("daily budget remaining count must be a non-negative integer")
        self.budget = budget
        self.remaining = remaining
        super().__init__(f"daily {budget} limit reached; {remaining} remaining")
