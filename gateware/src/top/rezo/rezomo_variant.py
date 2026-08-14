"""Compatibility import for the accepted REZOMO implementation.

REZOMO deliberately remains in ``top.py`` because this near-capacity design's
generated naming and packing are sensitive to its Python module path.
"""

try:
    from .top import *
    from .top import run_cli
except ImportError:
    from top import *
    from top import run_cli
