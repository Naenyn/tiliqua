"""Official 720x720 circular-display STREZO build entry point."""

try:
    from .targets import run_target
except ImportError:
    from targets import run_target


if __name__ == "__main__":
    run_target("strezo_round")
