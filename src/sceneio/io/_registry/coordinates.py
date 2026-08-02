"""Registry-facing access to the built-in coordinate manifest."""

from sceneio.coordinates import UNSPECIFIED_FORMAT_COORDINATES
from sceneio.io._coordinate_manifest import (
    FORMAT_COORDINATE_CONTRACTS,
    coordinate_contract,
)


def codec_coordinate_contract(format_id: str):
    """Return a built-in contract or the explicit extension fallback."""

    return FORMAT_COORDINATE_CONTRACTS.get(
        format_id,
        UNSPECIFIED_FORMAT_COORDINATES,
    )


__all__ = [
    "FORMAT_COORDINATE_CONTRACTS",
    "codec_coordinate_contract",
    "coordinate_contract",
]
