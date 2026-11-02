"""Load and save user-customized concept names and prompts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pose_director import CONCEPT_TEMPLATES


def settings_path() -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local_app_data / "VirtualFotostudio" / "concepts.json"


def default_concepts() -> dict[str, dict[str, str]]:
    return {key: {"name": key, "prompt": prompt} for key, prompt in CONCEPT_TEMPLATES.items()}


def validate_concepts(concepts: dict[str, dict[str, str]]) -> None:
    expected = set(CONCEPT_TEMPLATES)
    if set(concepts) != expected:
        raise ValueError("Concept settings do not match the built-in concept list.")
    names = []
    for key, concept in concepts.items():
        if not isinstance(concept, dict) or not isinstance(concept.get("name"), str) or not isinstance(
            concept.get("prompt"), str
        ):
            raise ValueError(f"Invalid saved settings for concept {key!r}.")
        name = concept["name"].strip()
        if not name:
            raise ValueError("Concept names cannot be empty.")
        names.append(name.casefold())
    if len(names) != len(set(names)):
        raise ValueError("Concept names must be unique.")


def load_concepts(path: Path | None = None) -> dict[str, dict[str, str]]:
    path = path or settings_path()
    if not path.exists():
        return default_concepts()
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse concept settings at {path}: {exc}") from exc
    if not isinstance(saved, dict) or saved.get("version") != 1 or not isinstance(saved.get("concepts"), dict):
        raise ValueError(f"Unsupported or invalid concept settings file: {path}")
    concepts = default_concepts()
    for key, value in saved["concepts"].items():
        if key not in concepts:
            raise ValueError(f"Unknown concept {key!r} in saved settings.")
        concepts[key] = value
    validate_concepts(concepts)
    return concepts


def save_concepts(concepts: dict[str, dict[str, str]], path: Path | None = None) -> None:
    path = path or settings_path()
    validate_concepts(concepts)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".concepts.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump({"version": 1, "concepts": concepts}, temporary, ensure_ascii=False, indent=2)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
