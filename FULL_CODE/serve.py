"""Start the web dashboard.

python FULL_CODE/serve.py               # then open http://127.0.0.1:8000
python FULL_CODE/serve.py --port 8001   # if port 8000 is already in use
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.server import create_app  # noqa: E402
from voice_of_store.cli import configure_logging  # noqa: E402
from voice_of_store.config import load_settings  # noqa: E402


def main() -> None:
    configure_logging()
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Start the Voice-of-Store dashboard.")
    parser.add_argument("--port", type=int, default=settings.server.port, help="port to listen on")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    uvicorn.run(create_app(settings), host=settings.server.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
