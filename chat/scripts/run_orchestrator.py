"""Run the FastAPI orchestrator from a source checkout.

The script is intentionally dependency-light so Playwright can launch the real
API both locally and in CI after ``uv sync``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "shared" / "contracts" / "src"),
    str(ROOT / "chat" / "knowledge" / "src"),
    str(ROOT / "chat" / "market" / "src"),
    str(ROOT / "chat" / "api" / "src"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MyFinance orchestrator API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=int(os.environ.get("CHAT_API_PORT", "8000")), type=int)
    parser.add_argument("--reload", action="store_true", help="Reload the API when source files change (development only).")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "myfinance_orchestrator.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(ROOT / "chat"), str(ROOT / "shared"), str(ROOT / "data")] if args.reload else None,
    )


if __name__ == "__main__":
    main()
