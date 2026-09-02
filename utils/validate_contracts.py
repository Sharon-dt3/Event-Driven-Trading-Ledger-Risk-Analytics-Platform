#!/usr/bin/env python3
"""Validate every TradePulse contract sample payload against its JSON Schema.

This is the Phase 0 "done" gate referenced by docs/contracts/README.md:

    python utils/validate_contracts.py

What it does
------------
- Loads every event JSON Schema under docs/contracts/events/*.schema.json into a
  referencing Registry keyed by each schema's $id, so relative "$ref" links
  (e.g. the per-event schemas referencing "envelope.schema.json") resolve.
- Validates each sample under docs/contracts/events/samples/<name>.sample.json
  against its matching <name>.schema.json using the Draft 2020-12 validator.
- Prints a PASS/FAIL line per sample and exits non-zero if anything fails or if
  an expected sample/schema pairing is missing.

It intentionally has one third-party dependency (jsonschema), which is the
standard, well-tested way to check JSON Schema conformance in Python.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
except ImportError as exc:  # pragma: no cover - clear guidance if deps missing
    print(
        "ERROR: missing dependency. Install with:\n"
        "    pip install jsonschema referencing\n"
        f"(import error: {exc})",
        file=sys.stderr,
    )
    sys.exit(2)

# Repo-root-relative paths (this file lives at <repo>/utils/validate_contracts.py).
REPO_ROOT = Path(__file__).resolve().parents[1]
EVENTS_DIR = REPO_ROOT / "docs" / "contracts" / "events"
SAMPLES_DIR = EVENTS_DIR / "samples"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def build_registry() -> Registry:
    """Register every event schema by its $id so relative $refs resolve."""
    registry = Registry()
    for schema_path in sorted(EVENTS_DIR.glob("*.schema.json")):
        schema = load_json(schema_path)
        resource = Resource.from_contents(schema)
        # Register under the schema's declared $id (used by relative $ref
        # resolution) and, defensively, under its bare filename.
        registry = resource @ registry
        if "$id" not in schema:
            registry = registry.with_resource(schema_path.name, resource)
    return registry


def discover_pairs() -> list[tuple[str, Path, Path]]:
    """Return (name, sample_path, schema_path) for each *.sample.json found."""
    pairs: list[tuple[str, Path, Path]] = []
    for sample_path in sorted(SAMPLES_DIR.glob("*.sample.json")):
        # tick_received.v1.sample.json -> tick_received.v1.schema.json
        name = sample_path.name[: -len(".sample.json")]
        schema_path = EVENTS_DIR / f"{name}.schema.json"
        pairs.append((name, sample_path, schema_path))
    return pairs


def main() -> int:
    if not SAMPLES_DIR.is_dir():
        print(f"ERROR: samples dir not found: {SAMPLES_DIR}", file=sys.stderr)
        return 2

    registry = build_registry()
    pairs = discover_pairs()
    if not pairs:
        print(f"ERROR: no *.sample.json files under {SAMPLES_DIR}", file=sys.stderr)
        return 2

    failures = 0
    for name, sample_path, schema_path in pairs:
        rel_sample = sample_path.relative_to(REPO_ROOT)
        if not schema_path.is_file():
            print(f"FAIL  {name}: no schema {schema_path.name} for {rel_sample}")
            failures += 1
            continue

        schema = load_json(schema_path)
        sample = load_json(sample_path)
        validator = Draft202012Validator(schema, registry=registry)
        errors = sorted(validator.iter_errors(sample), key=lambda e: list(e.path))
        if errors:
            failures += 1
            print(f"FAIL  {name}: {len(errors)} error(s) in {rel_sample}")
            for err in errors:
                loc = "/".join(str(p) for p in err.path) or "<root>"
                print(f"        - at {loc}: {err.message}")
        else:
            print(f"PASS  {name}: {rel_sample}")

    total = len(pairs)
    print(f"\n{total - failures}/{total} sample(s) valid.")
    if failures:
        print("Contract validation FAILED.", file=sys.stderr)
        return 1
    print("Contract validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
