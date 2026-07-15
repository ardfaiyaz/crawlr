"""Unified schema registry: built-in verticals + user-defined files (item 7).

Users can define new extraction schemas as YAML or JSON files in
`CRAWLR_SCHEMA_DIR` (default: <data dir>/schemas) without writing Python. This
turns Crawlr into a general-purpose tool for end users, not just developers:
new verticals (jobs, real estate, leads) become config, not code.

Example (jobs.yaml):

    name: jobs
    item_selector: ".job-card"
    fields:
      - name: title
        description: the job title
        type: text
        required: true
      - name: salary
        description: annual salary
        type: number
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from . import config
from .models import ExtractionSchema
from .verticals import ecommerce

_SUFFIXES = {".yaml", ".yml", ".json"}


def _parse_file(path: Path) -> ExtractionSchema:
    text = path.read_text()
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: top-level document must be a mapping")
    return ExtractionSchema.model_validate(data)


def load_user_schemas() -> dict[str, ExtractionSchema]:
    """Load and validate every schema file in SCHEMA_DIR (best-effort)."""
    out: dict[str, ExtractionSchema] = {}
    if not config.SCHEMA_DIR.exists():
        return out
    for path in sorted(config.SCHEMA_DIR.iterdir()):
        if path.suffix.lower() not in _SUFFIXES:
            continue
        try:
            schema = _parse_file(path)
        except (ValidationError, ValueError, yaml.YAMLError, json.JSONDecodeError):
            continue  # skip invalid files; `validate_file` surfaces the error
        out[schema.name] = schema
    return out


def resolve(name: str) -> ExtractionSchema | None:
    """Resolve a schema by name: user-defined schemas take precedence."""
    user = load_user_schemas()
    if name in user:
        return user[name]
    return ecommerce.resolve(name)


def available() -> list[dict]:
    """List all resolvable schemas with their source (built-in vs user)."""
    items: list[dict] = [
        {"name": name, "source": "built-in"}
        for name in ("product", "product_list")
    ]
    for name in load_user_schemas():
        items.append({"name": name, "source": "user"})
    return items


def validate_file(path: str | Path) -> tuple[bool, str]:
    """Validate a single schema file, returning (ok, message)."""
    p = Path(path)
    if not p.exists():
        return False, f"file not found: {p}"
    try:
        schema = _parse_file(p)
    except Exception as exc:
        return False, f"invalid schema: {exc}"
    return True, f"ok: schema '{schema.name}' with {len(schema.fields)} field(s)"
