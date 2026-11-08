"""gtui — design intelligence engine.

Capture what an application renders, infer the rules behind it, write them down with evidence
(the Aesthetic IR), and let coding agents apply them elsewhere.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gtui")
except PackageNotFoundError:  # pragma: no cover - editable/dev installs
    __version__ = "0.1.0"

__all__ = ["__version__"]
