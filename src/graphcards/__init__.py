"""Entity-backed flashcards scheduled with FSRS."""

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    """Return the installed distribution version for GraphCards."""

    return version("graphcards")


try:
    __version__ = package_version()
except PackageNotFoundError:
    # A source checkout can be imported without an installed distribution.
    __version__ = "0+unknown"


__all__ = ["__version__", "package_version"]
