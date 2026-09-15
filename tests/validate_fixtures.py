"""Validate the committed fixtures against the committed JSON Schemas.

Runs as ``python -m tests.validate_fixtures`` in CI. This is the check that
notices when a collector starts emitting a field the schema does not know
about, or stops emitting one it requires — a class of drift that unit tests
on individual functions will not catch, because each function still behaves
correctly in isolation.

Exit code is 0 when every fixture validates and 1 otherwise, so CI can rely on
it without parsing output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:  # pragma: no cover - CI installs the dev extras
    print("jsonschema is not installed; run: pip install -e '.[dev]'")
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
FIXTURE_DIR = ROOT / "tests" / "fixtures"

# Fixture file -> schema file. The mapping is explicit rather than inferred
# from the filename, because a fixture's name should be free to describe what
# scenario it represents.
PAIRS: list[tuple[str, str]] = [
    ("state.minimal.json", "state.schema.json"),
]


def load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def describe(error: jsonschema.ValidationError) -> str:
    """Render one validation error as a single readable line.

    The default repr buries the useful part under a wall of schema context.
    """
    location = "/".join(str(part) for part in error.absolute_path) or "(root)"
    return f"{location} :: {error.message}"


def validate_pair(fixture_name: str, schema_name: str) -> list[str]:
    fixture_path = FIXTURE_DIR / fixture_name
    schema_path = SCHEMA_DIR / schema_name

    if not fixture_path.exists():
        return [f"{fixture_name}: fixture is missing"]
    if not schema_path.exists():
        return [f"{schema_name}: schema is missing"]

    schema = load(schema_path)
    instance = load(fixture_path)

    # Draft202012 is what both schema files declare. Resolving the validator
    # from the $schema keyword rather than hard-coding the draft means a schema
    # bump does not need a code change here.
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)

    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    return [f"{fixture_name}: {describe(e)}" for e in errors]


def main() -> int:
    failures: list[str] = []

    for fixture_name, schema_name in PAIRS:
        problems = validate_pair(fixture_name, schema_name)
        if problems:
            failures.extend(problems)
            print(f"FAIL  {fixture_name} vs {schema_name}  ({len(problems)} problem(s))")
        else:
            print(f"ok    {fixture_name} vs {schema_name}")

    if failures:
        print()
        for line in failures[:40]:
            print("  -", line)
        if len(failures) > 40:
            print(f"  ... and {len(failures) - 40} more")
        return 1

    print("\nall fixtures validate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
