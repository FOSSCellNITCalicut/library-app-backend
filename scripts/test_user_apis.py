#!/usr/bin/env python3
"""
Test script for User Auth & Profile APIs (Phase 1).

Usage:
    python scripts/test_user_apis.py <roll_no> <password> [biblio_id]
"""

import sys
import json
import httpx

BASE = "http://localhost:8001"


def req(method, path, token=None, json_body=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    r = httpx.request(method, f"{BASE}{path}", headers=headers, json=json_body)
    return r.status_code, r.json() if r.text else {}


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check(label, status, expected, data=None):
    ok = status == expected
    status_str = f"HTTP {status}" + (f" (expected {expected})" if not ok else "")
    mark = "✅" if ok else "❌"
    print(f"  {mark} {label}: {status_str}")
    if data is not None:
        print(f"     {json.dumps(data, indent=4)}")
    return ok


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_user_apis.py <roll_no> <password> [biblio_id]")
        sys.exit(1)

    roll_no = sys.argv[1]
    password = sys.argv[2]
    biblio_id = int(sys.argv[3]) if len(sys.argv) > 3 else None

    passed = 0
    failed = 0

    def ok(status, expected=200):
        return status == expected

    # ------------- Health -------------
    section("1. Health Check")
    s, data = req("get", "/health")
    if check("GET /health", s, 200):
        passed += 1
    else:
        failed += 1

    # ------------- Login -------------
    section("2. POST /login")
    s, data = req("post", "/api/v1/login", json_body={
        "roll_no": roll_no,
        "password": password,
        "remember_me": False,
    })
    if check("POST /login", s, 200, data):
        passed += 1
    else:
        print(f"     Response: {data}")
        failed += 1
        sys.exit(1)

    access = data["access_token"]
    refresh = data["refresh_token"]

    # ------------- /user/me -------------
    section("3. GET /user/me")
    s, data = req("get", "/api/v1/user/me", token=access)
    if check("GET /user/me", s, 200, data):
        assert "roll_no" in data
        assert "name" in data
        assert "loan_summary" in data
        assert "checked_out_books" in data
        passed += 1
    else:
        failed += 1

    # ------------- /user/fines -------------
    section("4. GET /user/fines")
    s, data = req("get", "/api/v1/user/fines", token=access)
    if check("GET /user/fines", s, 200, data):
        assert "outstanding_fine" in data
        passed += 1
    else:
        failed += 1

    # ------------- /user/fines/history -------------
    section("5. GET /user/fines/history")
    s, data = req("get", "/api/v1/user/fines/history", token=access)
    if check("GET /user/fines/history", s, 200, data):
        assert "items" in data
        passed += 1
    else:
        failed += 1

    # ------------- /user/book-status/{id} -------------
    if biblio_id:
        section("6. GET /user/book-status/{biblio_id}")
        s, data = req("get", f"/api/v1/user/book-status/{biblio_id}", token=access)
        if check(f"GET /user/book-status/{biblio_id}", s, 200, data):
            assert "borrowed_by_current_user" in data
            passed += 1
        else:
            failed += 1
    else:
        print("\n  ⏭️  Skipping /user/book-status (no biblio_id provided)")

    # ------------- /auth/refresh -------------
    section("7. POST /auth/refresh")
    s, data = req("post", "/api/v1/auth/refresh", json_body={
        "refresh_token": refresh,
    })
    if check("POST /auth/refresh", s, 200, data):
        new_access = data["access_token"]
        passed += 1
    else:
        failed += 1
        sys.exit(1)

    # ------------- /user/me with new token -------------
    section("8. GET /user/me (after refresh)")
    s, data = req("get", "/api/v1/user/me", token=new_access)
    if check("GET /user/me (fresh token)", s, 200, data):
        passed += 1
    else:
        failed += 1

    # ------------- /auth/logout -------------
    section("9. POST /auth/logout")
    s, data = req("post", "/api/v1/auth/logout", token=new_access)
    if check("POST /auth/logout", s, 200):
        passed += 1
    else:
        failed += 1

    # ------------- Verify old token dead -------------
    section("10. GET /user/me (after logout - should fail)")
    s, data = req("get", "/api/v1/user/me", token=new_access)
    if check("GET /user/me (logged out)", s, 401):
        passed += 1
    else:
        failed += 1

    # ------------- Summary -------------
    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
