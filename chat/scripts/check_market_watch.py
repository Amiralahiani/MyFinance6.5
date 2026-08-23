"""Check the official Market Watch availability without collecting quotes."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "chat" / "market" / "src")]


def main() -> None:
    from myfinance_agent_market.market_watch import market_watch_collection_status

    status = market_watch_collection_status()
    print(f"Official Market Watch: {status['source_url']}")
    print(f"Collection status: {status['status']}")
    print(status["reason"])


if __name__ == "__main__":
    main()
