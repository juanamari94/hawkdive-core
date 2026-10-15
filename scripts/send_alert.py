"""Replay a Grafana notification against the local Hawkdive receiver."""

import argparse
import json
import os
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks/grafana/local")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    payload = json.loads(args.fixture.read_text(encoding="utf-8-sig"))
    token = os.getenv("HAWKDIVE_WEBHOOK_TOKEN", "local-dev-token")
    with httpx.Client(timeout=10) as client:
        for _ in range(args.repeat):
            response = client.post(
                args.url, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
            print(response.status_code, response.text)
            response.raise_for_status()


if __name__ == "__main__":
    main()
