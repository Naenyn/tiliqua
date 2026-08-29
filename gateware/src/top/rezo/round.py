"""Compatibility entry point for the historical REZOMO circular target."""

try:
    from .targets import run_target
except ImportError:
    from targets import run_target


if __name__ == "__main__":
    run_target("rezomo_round")
