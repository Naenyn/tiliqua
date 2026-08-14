"""Compatibility import for the historical REZOMO module path.

New builds use the explicit family entry points in :mod:`top.rezo.targets`.
Existing tests and downstream imports that reference ``top.rezo.top`` continue
to resolve to the accepted REZOMO implementation.
"""

try:
    from .rezomo_variant import *
except ImportError:  # Executed directly by legacy tooling.
    from rezomo_variant import *


if __name__ == "__main__":
    try:
        from .targets import run_target
    except ImportError:
        from targets import run_target
    run_target("rezomo")
