"""FreeAI Radar -- build-time collection and static site generation.

The architecture is deliberately a static site:

* the browser reads public JSON only
* Python runs at build and collection time only
* there is no resident FastAPI service, no online database, no admin write API
  and no unified online gateway

Importing this package registers every source adapter, which is what makes a
``parser:`` name in ``config/sources.yaml`` resolvable.
"""

from __future__ import annotations

__version__ = "0.1.0"

SCHEMA_VERSION = 1


def _register_adapters() -> None:
    """Import every adapter so the parser registry is populated.

    ``sources.yaml`` may only name parsers registered here. A parser that is
    never imported is a configuration error rather than a silent skip, so this
    runs at package import time.
    """
    from .collectors import (  # noqa: F401
        ailookup,
        awesome_freellm,
        free_llm,
        official_docs,
    )


_register_adapters()


def registered_parsers() -> list[str]:
    """Names accepted in ``sources.yaml``."""
    from .collectors.base import PARSER_REGISTRY

    return sorted(PARSER_REGISTRY)


__all__ = ["SCHEMA_VERSION", "__version__", "registered_parsers"]
