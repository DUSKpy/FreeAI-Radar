"""Base contract for source adapters.

Every source gets its own adapter. A single regex is never shared across
websites -- the task book is explicit that per-source rules win over generic
ones. The base class only supplies the shared plumbing: sentinel handling,
evidence construction and the ``parse_error`` guard.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from ..models import CandidateRecord
from ..parsers.markdown_tables import Provenance

PARSER_REGISTRY: dict[str, type[BaseAdapter]] = {}


class ParseError(RuntimeError):
    """Raised when a document's structure is unusable.

    The collector converts this into a ``parse_error`` source status. Existing
    data is never deleted as a result.
    """


@dataclass
class SourceSpec:
    """Runtime view of one entry from ``config/sources.yaml``."""

    id: str
    name: str
    url: str
    type: str
    source_family: str
    parser: str
    enabled: bool = True
    role: str = "directory"
    allowed_domains: list[str] = field(default_factory=list)
    license: str | None = None
    license_url: str | None = None
    terms_url: str | None = None
    provider_slug: str | None = None
    notes: str | None = None
    mirrors: list[str] = field(default_factory=list)
    parser_version: str = "1.0.0"

    @property
    def source_level(self) -> str:
        return "official" if self.role == "official" else "directory"


@dataclass
class ParseResult:
    """What an adapter returns for one fetched document."""

    candidates: list[CandidateRecord] = field(default_factory=list)
    #: Provider-level facts that are not per-model, e.g. a Base URL table.
    provider_facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Free-text notes for the verification queue when no field rule exists.
    review_notes: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    structure_ok: bool = True


class BaseAdapter(abc.ABC):
    """Interface every directory/official adapter implements."""

    #: Set by subclasses and used as the ``parser`` value in sources.yaml.
    name: str = "base"
    version: str = "1.0.0"

    def __init__(self, spec: SourceSpec) -> None:
        self.spec = spec

    # -- required ---------------------------------------------------------

    @abc.abstractmethod
    def parse(self, document: str, *, observed_at: str) -> ParseResult:
        """Turn raw document text into candidates plus provider facts."""

    # -- shared helpers ---------------------------------------------------

    def provenance(self, observed_at: str) -> Provenance:
        return Provenance(
            source_id=self.spec.id,
            source_record_url=self.spec.url,
            observed_at=observed_at,
            source_level=self.spec.source_level,
            source_family=self.spec.source_family,
        )

    def guard_empty(self, previous_count: int | None, new_count: int) -> bool:
        """Decide whether a collapse to zero looks like a structural failure.

        A source that used to yield many records and suddenly yields none is
        far more likely to have changed its markup than to have deleted its
        entire catalog. The collector marks ``parse_error`` and keeps the old
        data instead of emitting mass-removal events.
        """
        if new_count > 0:
            return True
        return not (previous_count or 0) >= 5

    def guard_shrink(self, previous_count: int | None, new_count: int) -> bool:
        """Detect a suspicious collapse such as 400 records down to 3."""
        if not previous_count or previous_count < 20:
            return True
        return new_count >= max(3, int(previous_count * 0.2))


def register(cls: type[BaseAdapter]) -> type[BaseAdapter]:
    """Register an adapter under its ``name`` for sources.yaml lookup."""
    PARSER_REGISTRY[cls.name] = cls
    return cls


def get_adapter(parser_name: str) -> type[BaseAdapter]:
    """Look up a registered adapter.

    ``sources.yaml`` may only reference parsers registered in this project.
    An unknown name is a hard configuration error, surfaced loudly rather than
    silently skipped.
    """
    if parser_name not in PARSER_REGISTRY:
        raise KeyError(
            f"parser '{parser_name}' is not registered; known parsers: {sorted(PARSER_REGISTRY)}"
        )
    return PARSER_REGISTRY[parser_name]
