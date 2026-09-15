"""State-handling contracts in ``radar.collect``.

These tests exist because the failure they guard against is *silent*. An empty
catalogue that builds successfully and deploys looks exactly like a catalogue
with no data yet -- and the task book is explicit that a fixture must never be
passed off as a real directory, and that an unreadable state must never be
treated as an empty one.

The three cases that must stay distinguishable:

1. genuine first run        -> ``--init``, state file legitimately absent
2. mistyped path            -> must fail loudly
3. unreadable / corrupt file -> must fail loudly

If (2) and (3) collapse into (1), a typo silently resets the collected history.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from radar.collect import CollectOptions, _empty_state, _load_previous

ROOT = Path(__file__).resolve().parent.parent


def _options(previous: Path | None, *, init: bool = False) -> CollectOptions:
    return CollectOptions(
        config_path=ROOT / "config" / "sources.yaml",
        previous_path=previous,
        output_path=ROOT / ".work" / "unused-state.json",
        init=init,
        dry_run=True,
    )


class TestLoadPrevious:
    """``_load_previous`` is the single gate between "no data" and "bad data"."""

    def test_missing_file_without_init_is_fatal(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        with pytest.raises(SystemExit) as excinfo:
            _load_previous(_options(missing))
        message = str(excinfo.value)
        assert "not found" in message
        # The error must say how to proceed, not just that something is wrong.
        assert "--init" in message

    def test_missing_file_with_init_starts_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        state, was_initial = _load_previous(_options(missing, init=True))
        assert was_initial is True
        assert state.providers == []
        assert state.collection_meta.initial_import_done is False

    def test_unreadable_file_is_not_treated_as_empty(self, tmp_path: Path) -> None:
        """A corrupt file must not become a fresh start, even with --init.

        --init authorises a *missing* file. It is not a blanket "ignore whatever
        is there", because that would let a truncated write erase history.
        """
        broken = tmp_path / "state.json"
        broken.write_text("{ this is not json", encoding="utf-8")

        with pytest.raises(SystemExit) as excinfo:
            _load_previous(_options(broken, init=True))
        message = str(excinfo.value)
        assert "cannot read" in message
        # Must be explicit that it refused rather than falling back.
        assert "Refusing" in message

    def test_valid_file_round_trips(self, tmp_path: Path, minimal_state: dict) -> None:
        path = tmp_path / "state.json"
        path.write_text(json.dumps(minimal_state), encoding="utf-8")

        state, was_initial = _load_previous(_options(path))
        assert was_initial is False
        assert state.schema_version == minimal_state["schema_version"]
        assert len(state.providers) == len(minimal_state["providers"])

    def test_schema_invalid_file_is_fatal(self, tmp_path: Path, minimal_state: dict) -> None:
        """Valid JSON that violates the schema must fail, not partially load."""
        payload = dict(minimal_state)
        payload["schema_version"] = "not-an-integer"
        path = tmp_path / "state.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(SystemExit) as excinfo:
            _load_previous(_options(path))
        assert "schema validation" in str(excinfo.value)

    def test_none_path_is_fatal_not_silent_empty(self) -> None:
        """The regression guard for the bug this file was written for.

        ``previous_path=None`` used to return an empty state with
        ``was_initial=True``, i.e. it silently pretended to be a first run.
        That made an omitted --previous indistinguishable from a real one.
        """
        with pytest.raises(SystemExit) as excinfo:
            _load_previous(_options(None))
        message = str(excinfo.value)
        assert "--previous" in message
        assert "previous state path" in message


class TestEmptyState:
    def test_initial_state_is_honestly_empty(self) -> None:
        """No fabricated timestamps: an empty state has no successful collection."""
        state = _empty_state()
        meta = state.collection_meta
        assert meta.last_successful_collection_at is None
        assert meta.last_complete_collection_at is None
        assert meta.initial_import_done is False

    def test_initial_state_has_no_entities(self) -> None:
        state = _empty_state()
        assert state.providers == []
        assert state.models == []
        assert state.offers == []
        assert state.claims == []
        # An empty catalogue must not invent a change either.
        assert state.changes == []


class TestCliContract:
    """``--previous`` is required, and the CLI must enforce it."""

    @staticmethod
    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "radar.collect", *args],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )

    def test_previous_is_required(self) -> None:
        result = self._run("--dry-run")
        assert result.returncode != 0
        assert "--previous" in result.stderr

    def test_missing_path_without_init_fails(self, tmp_path: Path) -> None:
        result = self._run("--previous", str(tmp_path / "nope.json"), "--dry-run")
        assert result.returncode != 0
        assert "--init" in result.stderr or "--init" in result.stdout

    def test_help_mentions_the_typo_hazard(self) -> None:
        """The reason --previous is required should be visible in --help.

        A future maintainer who finds the requirement annoying should be able
        to see why it exists before quietly relaxing it.
        """
        result = self._run("--help")
        assert result.returncode == 0
        assert "typo" in result.stdout.lower()
