from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import zipfile
from importlib.metadata import version
from importlib.resources.abc import Traversable
from pathlib import Path

import pytest

from graphcards.config import load_config
from graphcards.decks import Deck
from graphcards.scaffold import available_templates, initialize_user_setup, initialize_workspace


def test_package_version_matches_distribution_metadata() -> None:
    from graphcards import package_version

    assert package_version() == version("graphcards")


def _files(root: Path | Traversable, relative: Path = Path()) -> dict[Path, Path | Traversable]:
    found: dict[Path, Path | Traversable] = {}
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        child_relative = relative / child.name
        if child.is_dir():
            found.update(_files(child, child_relative))
        elif child.is_file():
            found[child_relative] = child
    return found


def test_importlib_resources_expose_every_template_without_user_config() -> None:
    from importlib.resources import files

    root = files("graphcards").joinpath("templates")
    if not root.is_dir():
        # A source checkout intentionally keeps the canonical tree at repository root.
        root = Path(__file__).parents[1] / "templates"
    resource_files = _files(root)
    names = {relative.parts[0] for relative in resource_files}

    assert names == set(available_templates())
    assert resource_files
    assert not any(
        relative.name in {"config.toml", "graphcards.toml"} for relative in resource_files
    )
    assert (
        resource_files[Path("image-occlusion/assets/solar-system.jpg")]
        .read_bytes()
        .startswith(b"\xff\xd8\xff")
    )


def test_user_setup_and_init_copy_only_deck_and_required_assets(tmp_path: Path) -> None:
    config_path = initialize_user_setup(tmp_path / "profile" / "config.toml")
    config = load_config(config_path)
    template_root = config.templates_paths[0]
    template_names = available_templates(config.templates_paths)

    assert template_names
    assert not any(
        path.name in {"config.toml", "graphcards.toml"} for path in template_root.rglob("*")
    )
    for template_name in template_names:
        destination = initialize_workspace(
            tmp_path / "decks" / template_name,
            template_name,
            "json",
            config.templates_paths,
        )
        files = {path.relative_to(destination) for path in destination.rglob("*") if path.is_file()}
        expected = {Path("deck.json")}
        if template_name == "image-occlusion":
            expected.add(Path("assets/solar-system.jpg"))
        assert files == expected


def test_first_configured_template_directory_wins_on_name_overlap(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "templates" / "analogy-capitals"
    first = tmp_path / "first"
    second = tmp_path / "second"
    shutil.copytree(source, first / "analogy-capitals")
    shutil.copytree(source, second / "analogy-capitals")
    (first / "analogy-capitals" / "deck.json").write_text(
        (first / "analogy-capitals" / "deck.json")
        .read_text(encoding="utf-8")
        .replace('"name": "Capital recall"', '"name": "First template"'),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'templates_paths = ["{first}", "{second}"]\n', encoding="utf-8")

    config = load_config(config_path)
    destination = initialize_workspace(
        tmp_path / "deck", "analogy-capitals", template_paths=config.templates_paths
    )

    assert Deck.load(destination / "deck.json").display_name == "First template"
    assert available_templates(config.templates_paths).count("analogy-capitals") == 1


def test_supplied_wheel_and_source_distribution_contain_runtime_resources() -> None:
    wheel_name = os.environ.get("GRAPHCARDS_WHEEL")
    source_name = os.environ.get("GRAPHCARDS_SDIST")
    if not wheel_name or not source_name:
        pytest.skip("set GRAPHCARDS_WHEEL and GRAPHCARDS_SDIST to run clean artifact checks")

    wheel = Path(wheel_name)
    source = Path(source_name)
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata = archive.read(
            next(name for name in names if name.endswith(".dist-info/METADATA"))
        )
        entry_points = archive.read(
            next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        )
        assert "graphcards/templates/image-occlusion/assets/solar-system.jpg" in names
        assert any(name.startswith("graphcards/templates/") for name in names)
        assert not any(name.endswith("/config.toml") for name in names)
        assert b"Name: graphcards" in metadata
        assert b"Version: 0.1.0" in metadata
        assert b"graphcards = graphcards.cli:main" in entry_points

    with tarfile.open(source) as archive:
        names = set(archive.getnames())
        assert any(
            name.endswith("/templates/image-occlusion/assets/solar-system.jpg") for name in names
        )
        assert any(name.endswith("/docs/tutorials/getting-started.md") for name in names)
        assert not any(name.endswith("/templates/config.toml") for name in names)


def test_supplied_clean_python_runs_installed_console_script(tmp_path: Path) -> None:
    wheel_name = os.environ.get("GRAPHCARDS_WHEEL")
    python_name = os.environ.get("GRAPHCARDS_TEST_PYTHON")
    if not wheel_name or not python_name:
        pytest.skip("set GRAPHCARDS_WHEEL and GRAPHCARDS_TEST_PYTHON for clean install checks")

    python = Path(python_name)
    subprocess.run([str(python), "-m", "pip", "install", wheel_name], check=True)
    graphcards = python.with_name("graphcards")
    profile = tmp_path / "profile"
    result = subprocess.run(
        [str(graphcards), "--config", str(profile / "config.toml"), "setup"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Created user-wide GraphCards setup" in result.stdout
    assert (profile / "config.toml").is_file()
    assert (profile / "templates" / "image-occlusion" / "assets" / "solar-system.jpg").is_file()
