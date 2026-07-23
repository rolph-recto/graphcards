"""Create empty or template-based RDFCards workspaces from package resources."""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from rdfcards.errors import ConfigError


def available_templates() -> tuple[str, ...]:
    """Return the sorted names accepted by ``init --template``."""

    templates_root = files("rdfcards").joinpath("templates")
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


def initialize_workspace(directory: Path, template: str | None = None) -> None:
    """Copy an entire bundled template without overwriting existing files."""

    templates_root = files("rdfcards").joinpath("templates")
    # Every packaged directory except the reserved empty workspace is a named
    # template, so adding one does not require a Python registry change.
    available = available_templates()
    if template is not None and template not in available:
        names = ", ".join(available) or "none"
        raise ConfigError(f"unknown template {template!r}; available templates: {names}")
    template_name = template or "empty"
    template_root = templates_root.joinpath(template_name)
    resources = _template_files(template_root)
    root = directory.expanduser().resolve()
    destinations = tuple(root / relative for relative, _resource in resources)
    # Preflight the entire template so a collision cannot leave a partial workspace.
    existing = [path for path in destinations if path.exists()]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise ConfigError(f"refusing to overwrite existing files: {joined}")

    for destination, (_relative, resource) in zip(destinations, resources, strict=True):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(resource.read_text(encoding="utf-8"), encoding="utf-8")
