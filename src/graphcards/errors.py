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
