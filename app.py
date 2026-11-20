"""Remote Video Monitoring — application entry point.

After activating the project virtual environment, launch from this
directory with one command:

    python app.py

Optional flags are documented in README.md and in `python app.py --help`.
"""

from __future__ import annotations

from video_monitor.config import parse_args
from video_monitor.server import run_server


def main(argv: list[str] | None = None) -> None:
    config = parse_args(argv)
    run_server(config)


if __name__ == "__main__":
    main()
