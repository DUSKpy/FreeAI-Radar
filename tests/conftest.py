"""Shared test helpers.

Fixtures here are deliberately small and hand-built rather than captured from a
live run: a test that depends on today's upstream content is a test that fails
tomorrow for no reason.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def free_llm_readme() -> str:
    return (FIXTURES / "free-llm-readme.md").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def awesome_readme() -> str:
    return (FIXTURES / "awesome-freellm-readme.md").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def ailookup_readme() -> str:
    return (FIXTURES / "ailookup-readme.md").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def minimal_state() -> dict:
    return json.loads((FIXTURES / "state.minimal.json").read_text(encoding="utf-8"))


@pytest.fixture
def state_copy(minimal_state: dict) -> dict:
    """A deep copy, so a test mutating state cannot affect the next test."""
    return copy.deepcopy(minimal_state)
