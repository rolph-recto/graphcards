class RdfCardsError(Exception):
    """Base class for errors that should be shown directly to CLI users."""


class ConfigError(RdfCardsError):
    """The project configuration is invalid."""


class PresentationError(RdfCardsError):
    """A presentation query or its results are invalid."""


class StorageError(RdfCardsError):
    """Persistent state is inconsistent or cannot be updated safely."""


class StaleReviewError(StorageError):
    """A review was based on a card schedule that is no longer current."""
