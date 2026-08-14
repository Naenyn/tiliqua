"""Standard 1280x720 REZOMO build entry point."""

try:
    from .targets import run_target
except ImportError:
    from targets import run_target


if __name__ == "__main__":
    run_target("rezomo")
