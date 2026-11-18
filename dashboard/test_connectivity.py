#!/usr/bin/env python3
"""Read-only diagnostic against the configured live Paperclip (no .env required)."""
from app import COMPANY_ID, PAPERCLIP_URL, PaperclipError, list_agents_from_paperclip, paperclip_json


def main() -> int:
    print(f"Paperclip: {PAPERCLIP_URL} | company: {COMPANY_ID or '(auto)'}")
    try:
        health = paperclip_json("/api/health")
        if not isinstance(health, dict) or health.get("status") != "ok":
            print("Paperclip is not ready. Check the URL and the npm start terminal.")
            return 1
        print("Paperclip /api/health: ok")
        agents = list_agents_from_paperclip()["agents"]
    except (PaperclipError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Company accessible; {len(agents)} agent(s). Herdr is not required for this check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
