"""Local REPL for the commerce orchestrator.

    uv run python scripts/chat.py                 # anonymous session
    AUTH_TOKEN=<jwt> uv run python scripts/chat.py # pre-authenticated session

Needs AWS credentials for Bedrock and a reachable ECOMMERCE_API_BASE_URL.
Type 'quit' to exit, 'state' to dump session data.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.orchestrator_agent import OrchestratorAgent  # noqa: E402
from utils.logger_config import LoggerConfig  # noqa: E402


def main() -> None:
    orch = OrchestratorAgent(LoggerConfig())
    details = {"channel": "CHAT", "role": os.getenv("ROLE", "customer")}
    if os.getenv("AUTH_TOKEN"):
        details["authToken"] = os.environ["AUTH_TOKEN"]
    if os.getenv("USER_ID"):
        details["userId"] = os.environ["USER_ID"]

    print("commerce-bot — type 'quit' to exit, 'state' to dump session data\n")
    last_data: dict = {}
    while True:
        try:
            msg = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg:
            continue
        if msg in {"quit", "exit"}:
            break
        if msg == "state":
            print(json.dumps(last_data, indent=2, default=str))
            continue

        reply, last_data = orch.run(msg, details)
        print(f"\nbot> {reply}\n")


if __name__ == "__main__":
    main()
