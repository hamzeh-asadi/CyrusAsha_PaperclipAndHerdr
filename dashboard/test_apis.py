#!/usr/bin/env python3
"""
Simple test runner for dashboard APIs.
Run with: python dashboard/test_apis.py
"""

import os
import sys
import json
import time

# Make sure the dashboard directory (this script's own directory) is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import (
    PAPERCLIP_URL,
    COMPANY_ID,
    DashboardHandler,
    check_paperclip_online,
    list_agents_from_paperclip,
)


def test_paperclip_online():
    print("=== Test 1: Check Paperclip Online Status ===")
    online = check_paperclip_online()
    print(f"  Paperclip online: {online}")
    print("")


def test_list_agents():
    print("=== Test 2: List Agents from Paperclip ===")
    try:
        result = list_agents_from_paperclip()
        print(f"  Paperclip online: {result.get('paperclip_online', False)}")
        agents = result.get('agents', [])
        print(f"  Found {len(agents)} agents")
        for agent in agents:
            print(f"    - {agent.get('name')} ({agent.get('adapterType')})")
    except Exception as e:
        print(f"  Error: {e}")
    print("")


def test_health_endpoint():
    print("=== Test 3: Exercise /health through the request handler ===")
    # The handler needs a live socket in __init__, so build the instance directly
    # and route a fake /health request through do_GET().
    handler = object.__new__(DashboardHandler)
    handler.path = "/health"
    captured = {}
    handler.send_json = lambda data, status=200: captured.update({"status": status, "data": data})

    handler.do_GET()
    print(f"  Status: {captured.get('status')}")
    print(f"  Body: {json.dumps(captured.get('data'), ensure_ascii=False)}")
    print("")


def run_all_tests():
    print("=" * 60)
    print("Dashboard API Tests")
    print("=" * 60)
    print("")

    # Configuration was already resolved when app was imported
    # (real env vars, then dashboard/.env, then code defaults).
    print(f"  Paperclip API: {PAPERCLIP_URL}")
    print(f"  Company ID:    {COMPANY_ID}")
    print("")

    test_paperclip_online()
    time.sleep(1)
    test_list_agents()
    time.sleep(1)
    test_health_endpoint()

    print("=" * 60)
    print("Tests completed")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
