"""Package-version lookup for runtime governance metadata."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


# Kept as a fallback for source-tree execution where distribution metadata is absent.
__version__ = "0.13.0"


def package_version() -> str:
    try:
        return version("agentic-governance")
    except PackageNotFoundError:
        return __version__


PACKAGE_VERSION = package_version()
