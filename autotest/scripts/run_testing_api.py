"""Run the independent Agentic Testing FastAPI service from a source checkout."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "shared" / "contracts" / "src"),
    str(ROOT / "chat" / "knowledge" / "src"),
    str(ROOT / "chat" / "api" / "src"),
    str(ROOT / "autotest" / "src"),
    str(ROOT / "autotest" / "api"),
]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "myfinance_testing_api.main:app",
        host=os.environ.get("TESTING_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("TESTING_API_PORT", "8001")),
    )
