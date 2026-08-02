"""Create decks and user-wide GraphCards template libraries."""

from __future__ import annotations

import os
from collections.abc import Sequence
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from graphcards.errors import ConfigError

TEMPLATE_FORMATS = ("json", "toml", "yaml")
_USER_CONFIG = 'templates_paths = ["templates"]\n'


def _templates_root() -> Traversable | Path:
    """Return template resources from a checkout or an installed package."""

    checkout_root = Path(__file__).parents[2] / "templates"
    if checkout_root.is_dir():
        return checkout_root
    return files("graphcards").joinpath("templates")


def _template_roots(template_paths: Sequence[Path] | None) -> tuple[Traversable | Path, ...]:
    if template_paths is None:
        return (_templates_root(),)
    return tuple(template_paths)


def _directory_entries(directory: Traversable | Path) -> tuple[Traversable | Path, ...]:
    if isinstance(directory, Path) and os.path.lexists(directory) and not directory.is_dir():
        raise ConfigError(f"template path is not a directory: {directory}")
    try:
        return tuple(sorted(directory.iterdir(), key=lambda item: item.name))
    except NotADirectoryError as error:
        raise ConfigError(f"template path is not a directory: {directory}") from error
    except OSError:
        return ()


def available_templates(template_paths: Sequence[Path] | None = None) -> tuple[str, ...]:
    """Return unique template names in configured path order.

    The first directory that contains a name supplies that template. When no
    paths are supplied, the built-in checkout or package resources are used.
    """

    names: list[str] = []
    seen: set[str] = set()
    for templates_root in _template_roots(template_paths):
        for resource in _directory_entries(templates_root):
            if resource.name == "empty" or resource.name in seen or not resource.is_dir():
                continue
            seen.add(resource.name)
            names.append(resource.name)
    return tuple(names)


def _template_files(
    directory: Traversable | Path, relative: Path = Path()
) -> tuple[tuple[Path, Traversable | Path], ...]:
    """Flatten a resource directory into destination-relative files."""

    found: list[tuple[Path, Traversable | Path]] = []
    for resource in _directory_entries(directory):
        resource_path = relative / resource.name
        if resource.is_dir():
            found.extend(_template_files(resource, resource_path))
        elif resource.is_file():
            found.append((resource_path, resource))
    return tuple(found)


def _template_library_files(
    templates_root: Traversable | Path,
) -> tuple[tuple[Path, Traversable | Path], ...]:
    """Return all user-copyable files from the built-in template library."""

    files_to_copy: list[tuple[Path, Traversable | Path]] = []
    for template in _directory_entries(templates_root):
        if not template.is_dir() or template.name == "empty":
            continue
        for relative, resource in _template_files(template, Path(template.name)):
            # Older source trees used this file for a workspace configuration.
            # A user-wide config is created separately and is never a template.
            if relative.name in {"config.toml", "graphcards.toml"}:
                continue
            files_to_copy.append((relative, resource))
    return tuple(files_to_copy)


def _find_template(
    template: str,
    template_paths: Sequence[Path] | None,
) -> Traversable | Path:
    if not template.strip() or Path(template).name != template or template in {".", ".."}:
        raise ConfigError(f"invalid template name {template!r}")
    for templates_root in _template_roots(template_paths):
        candidate = templates_root.joinpath(template)
        if candidate.is_dir():
            return candidate
    names = ", ".join(available_templates(template_paths)) or "none"
    raise ConfigError(f"unknown template {template!r}; available templates: {names}")


def _selected_template_files(
    template_root: Traversable | Path,
    deck_format: str,
) -> tuple[tuple[Path, Traversable | Path], ...]:
    if deck_format not in TEMPLATE_FORMATS:
        choices = ", ".join(TEMPLATE_FORMATS)
        raise ConfigError(f"unsupported deck format {deck_format!r}; choose {choices}")

    deck_name = f"deck.{deck_format}"
    deck = template_root.joinpath(deck_name)
    if not deck.is_file():
        choices = (
            ", ".join(
                resource.name
                for resource in _directory_entries(template_root)
                if resource.name.startswith("deck.") and resource.is_file()
            )
            or "none"
        )
        message = (
            f"template does not provide deck format {deck_format!r}; "
            f"available deck files: {choices}"
        )
        raise ConfigError(message)

    selected = [(Path(deck_name), deck)]
    assets = template_root.joinpath("assets")
    if assets.is_dir():
        selected.extend(_template_files(assets, Path("assets")))
    return tuple(selected)


def _symlink_component(path: Path, root: Path) -> Path | None:
    current = root
    for component in path.relative_to(root).parts:
        current /= component
        if current.is_symlink():
            return current
    return None


def _symlink_ancestor(path: Path) -> Path | None:
    current = path
    while current != current.parent:
        if current.is_symlink():
            return current
        current = current.parent
    return None


def _absolute_path(path: Path, description: str) -> Path:
    try:
        expanded = path.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        return Path(os.path.abspath(expanded))
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ConfigError(f"could not resolve {description} {path}: {error}") from error


def initialize_workspace(
    directory: Path,
    template: str | None = None,
    deck_format: str = "json",
    template_paths: Sequence[Path] | None = None,
) -> Path:
    """Create one deck and its required assets without changing user config.

    ``template_paths`` is ordered. The first configured directory containing
    ``template`` wins. If it is omitted, the built-in source or package
    resources are used. A missing template creates an empty directory.
    """

    root = _absolute_path(directory, "workspace path")
    symlinked_root = _symlink_ancestor(root)
    if symlinked_root is not None:
        raise ConfigError(f"refusing to write through symlinked workspace path: {symlinked_root}")

    resources: tuple[tuple[Path, Traversable | Path], ...] = ()
    if template is not None:
        resources = _selected_template_files(_find_template(template, template_paths), deck_format)

    destinations = tuple(root / relative for relative, _resource in resources)
    symlinked = [path for path in destinations if _symlink_component(path, root) is not None]
    if symlinked:
        joined = ", ".join(str(path) for path in symlinked)
        raise ConfigError(f"refusing to write through symlinked workspace paths: {joined}")
    existing = [path for path in destinations if path.exists()]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise ConfigError(f"refusing to overwrite existing files: {joined}")

    try:
        root.mkdir(parents=True, exist_ok=True)
        for destination, (_relative, resource) in zip(destinations, resources, strict=True):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(resource.read_bytes())
    except (OSError, ValueError) as error:
        raise ConfigError(f"could not initialize workspace {root}: {error}") from error
    return root


def initialize_user_setup(config_path: Path) -> Path:
    """Create a user-wide config and copy the packaged template library."""

    resolved_config = _absolute_path(config_path, "configuration path")
    template_directory = resolved_config.parent / "templates"
    symlinked = _symlink_ancestor(resolved_config) or _symlink_ancestor(template_directory)
    if symlinked is not None:
        raise ConfigError(f"refusing to write through symlinked user path: {symlinked}")

    resources = _template_library_files(_templates_root())
    destinations = tuple(template_directory / relative for relative, _resource in resources)
    if resolved_config.exists():
        raise ConfigError(f"refusing to overwrite existing configuration: {resolved_config}")
    existing = [path for path in destinations if path.exists()]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise ConfigError(f"refusing to overwrite existing template files: {joined}")

    try:
        template_directory.mkdir(parents=True, exist_ok=True)
        for destination, (_relative, resource) in zip(destinations, resources, strict=True):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(resource.read_bytes())
        resolved_config.write_text(_USER_CONFIG, encoding="utf-8")
    except (OSError, ValueError) as error:
        raise ConfigError(f"could not create user-wide GraphCards setup: {error}") from error
    return resolved_config


__all__ = [
    "TEMPLATE_FORMATS",
    "available_templates",
    "initialize_user_setup",
    "initialize_workspace",
]
