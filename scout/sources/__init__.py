"""Pluggable data-source connectors.

Each connector yields `Company` records from a public source. Connectors are
registered by name so the pipeline / CLI can select sources at runtime.
"""

from __future__ import annotations

from .base import Source
from .delaware import DelawareSource
from .delaware_icis import DelawareIcisSource
from .sample import SampleSource
from .sec_edgar import SecEdgarSource

REGISTRY: dict[str, type[Source]] = {
    SampleSource.name: SampleSource,
    DelawareSource.name: DelawareSource,
    DelawareIcisSource.name: DelawareIcisSource,
    SecEdgarSource.name: SecEdgarSource,
}


def get_source(name: str, **kwargs) -> Source:
    if name not in REGISTRY:
        raise KeyError(
            f"Unknown source '{name}'. Available: {', '.join(sorted(REGISTRY))}"
        )
    return REGISTRY[name](**kwargs)


__all__ = [
    "Source", "SampleSource", "DelawareSource", "DelawareIcisSource",
    "SecEdgarSource", "REGISTRY", "get_source",
]
