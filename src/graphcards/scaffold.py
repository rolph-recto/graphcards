"""Create empty or template-based GraphCards workspaces."""

from __future__ import annotations

import os
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from graphcards.errors import ConfigError


def available_templates() -> tuple[str, ...]:
    """Return the sorted names accepted by ``init --template``."""

    templates_root = files("graphcards").joinpath("templates")
    # "empty" supplies the default workspace and is not a named template.
    return tuple(
        resource.name
        for resource in sorted(templates_root.iterdir(), key=lambda item: item.name)
        if resource.is_dir() and resource.name != "empty"
    )


def _template_files(
    directory: Traversable, relative: Path = Path()
) -> tuple[tuple[Path, Traversable], ...]:
    """Flatten a packaged template tree into destination-relative resources."""

    found: list[tuple[Path, Traversable]] = []
    for resource in sorted(directory.iterdir(), key=lambda item: item.name):
        resource_path = relative / resource.name
        if resource.is_dir():
            found.extend(_template_files(resource, resource_path))
        elif resource.is_file():
            found.append((resource_path, resource))
    return tuple(found)


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


def initialize_workspace(directory: Path, template: str | None = None) -> Path:
    """Copy an entire bundled template without overwriting existing files."""

    templates_root = files("graphcards").joinpath("templates")
    # Every packaged directory except the reserved empty workspace is a named
    # template, so adding one does not require a Python registry change.
    available = available_templates()
    if template is not None and template not in available:
        names = ", ".join(available) or "none"
        raise ConfigError(f"unknown template {template!r}; available templates: {names}")
    template_name = template or "empty"
    template_root = templates_root.joinpath(template_name)
    resources = _template_files(template_root)
    try:
        expanded = directory.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        expanded = Path(os.path.abspath(expanded))
        symlinked_root = _symlink_ancestor(expanded)
        if symlinked_root is not None:
            raise ConfigError(
                f"refusing to write through symlinked workspace path: {symlinked_root}"
            )
        root = expanded.resolve()
    except ConfigError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ConfigError(f"could not resolve workspace path {directory}: {error}") from error
    destinations = tuple(root / relative for relative, _resource in resources)
    # Preflight the entire template so a collision cannot leave a partial workspace.
    symlinked = [path for path in destinations if _symlink_component(path, root) is not None]
    if symlinked:
        joined = ", ".join(str(path) for path in symlinked)
        raise ConfigError(f"refusing to write through symlinked workspace paths: {joined}")
    existing = [path for path in destinations if path.exists()]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise ConfigError(f"refusing to overwrite existing files: {joined}")

    for destination, (_relative, resource) in zip(destinations, resources, strict=True):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(resource.read_bytes())
    return root
