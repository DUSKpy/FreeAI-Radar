"""Guards on what the repository tracks.

`.gitignore` mistakes are among the most expensive kind: they are silent, they
only show up when a file is needed, and by then the history is wrong. Two real
hazards this file pins down:

1. A bare ``state.json`` pattern matches at *any* depth. It would swallow
   ``data/seed/state.empty.json``, the committed cold-start seed that the
   tests and docs depend on. The pattern must stay anchored.
2. Conversely, a real local state file and anything key-shaped must actually be
   ignored, or a maintainer's local run leaks into the repository.

Rather than reason about glob semantics in the abstract, these tests build a
throwaway git repository and ask git itself.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GITIGNORE = ROOT / ".gitignore"

#: Files that MUST be committable. If the ignore rules ever swallow one of
#: these, the build breaks for everyone who clones.
MUST_BE_TRACKED = (
    "data/seed/state.empty.json",
    "data/seed/README.md",
    "tests/fixtures/state.minimal.json",
    "config/sources.yaml",
    "config/reviews.yaml",
    "config/aliases.yaml",
    "schemas/state.schema.json",
    "schemas/catalog.schema.json",
)

#: Files that MUST be ignored. A leak here is a credential or state leak.
MUST_BE_IGNORED = (
    "state.json",
    "data/state.json",
    ".env",
    ".env.local",
    "deploy.key",
    "dist/index.html",
    ".work/state.json",
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not available on PATH")


@pytest.fixture(scope="module")
def scratch_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A minimal repo carrying only this project's .gitignore."""
    repo = tmp_path_factory.mktemp("gitignore-check")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    shutil.copy(GITIGNORE, repo / ".gitignore")

    for relative in MUST_BE_TRACKED + MUST_BE_IGNORED:
        candidate = repo / relative
        candidate.parent.mkdir(parents=True, exist_ok=True)
        # Content is irrelevant; only the path matters to git.
        candidate.write_text("placeholder\n", encoding="utf-8")
    return repo


def _is_ignored(repo: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative],
        cwd=repo,
        capture_output=True,
    )
    # 0 == ignored, 1 == not ignored, 128 == error
    if result.returncode not in (0, 1):
        raise AssertionError(f"git check-ignore failed for {relative}: {result.stderr.decode()}")
    return result.returncode == 0


class TestGitignore:
    def test_required_files_are_committable(self, scratch_repo: Path) -> None:
        swallowed = [
            relative for relative in MUST_BE_TRACKED if _is_ignored(scratch_repo, relative)
        ]
        assert not swallowed, (
            "these required files are ignored by .gitignore: "
            f"{swallowed}. A bare 'state.json' pattern matches at any depth -- "
            "anchor it with a leading slash."
        )

    def test_secrets_and_state_are_ignored(self, scratch_repo: Path) -> None:
        leaking = [
            relative for relative in MUST_BE_IGNORED if not _is_ignored(scratch_repo, relative)
        ]
        assert not leaking, f"these should be ignored but are not: {leaking}"

    def test_the_real_seed_file_exists(self) -> None:
        """The ignore rules protect a file that must actually be present."""
        seed = ROOT / "data" / "seed" / "state.empty.json"
        assert seed.exists(), f"{seed} is referenced by docs and tests but missing"

    def test_the_committed_seed_is_genuinely_empty(self) -> None:
        """The seed must stay empty.

        If someone ever 'helpfully' fills it with sample providers, the publish
        workflow could push fabricated data as if it were a real directory,
        which the task book forbids outright.
        """
        import json

        seed = ROOT / "data" / "seed" / "state.empty.json"
        payload = json.loads(seed.read_text(encoding="utf-8"))

        for entity in ("providers", "models", "offers", "claims", "changes", "sources"):
            assert payload[entity] == [], (
                f"data/seed/state.empty.json has {len(payload[entity])} entries in "
                f"'{entity}'. The seed must stay empty -- it exists so the "
                "'no data yet' path is testable, not to hold sample data."
            )

        meta = payload["collection_meta"]
        assert meta["last_successful_collection_at"] is None
        assert meta["last_complete_collection_at"] is None
        assert meta["initial_import_done"] is False

    def test_the_seed_matches_the_code_generated_shape(self) -> None:
        """A hand-edited seed would drift from the model. Prove it has not."""
        import json

        from radar.collect import _empty_state

        seed = ROOT / "data" / "seed" / "state.empty.json"
        on_disk = json.loads(seed.read_text(encoding="utf-8"))
        generated = _empty_state().model_dump(mode="json")

        # Timestamps differ by construction; compare the shape and every
        # other value.
        assert set(on_disk) == set(generated)
        for key in on_disk:
            if key in {"created_at", "updated_at"}:
                continue
            assert on_disk[key] == generated[key], (
                f"data/seed/state.empty.json differs from _empty_state() at "
                f"'{key}'. Regenerate it rather than editing by hand."
            )
