#!/usr/bin/env python3
"""User management for the door API (users.toml).

Usage:
    python manage_users.py list
    python manage_users.py add NAME --profile total|parcial
    python manage_users.py rotate NAME           # generates a new API key
    python manage_users.py profile NAME total|parcial
    python manage_users.py disable NAME
    python manage_users.py enable NAME
    python manage_users.py remove NAME

After any change, restart the service (e.g. sudo systemctl restart door)
"""
from pathlib import Path
import argparse
import hashlib
import secrets
import tomllib
import json
import os
import re
import sys

BASE_DIR   = Path(os.environ.get("DOOR_DIR", Path(__file__).resolve().parent))
USERS_PATH = BASE_DIR / "users.toml"

# Must match the PROFILES keys in door.py
PROFILES = ("total", "parcial")
NAME_RE  = re.compile(r"^[\w.-]{1,40}$")

def _hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()

def _load() -> list[dict]:
    if not USERS_PATH.exists():
        return []
    with open(USERS_PATH, "rb") as f:
        return tomllib.load(f).get("users", [])

def _save(users: list[dict]):
    lines = [
        "# Door API users. Manage with manage_users.py",
        "# profile: total (calle, portal, ambas) | parcial (calle only)",
        "",
    ]
    for u in users:
        lines += [
            "[[users]]",
            f"name = {json.dumps(u['name'])}",
            f"profile = {json.dumps(u['profile'])}",
            f"active = {'true' if u.get('active', True) else 'false'}",
            f"key_sha256 = {json.dumps(u['key_sha256'])}",
            "",
        ]
    tmp = USERS_PATH.with_suffix(".tmp")
    fd  = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines))
    os.replace(tmp, USERS_PATH)

def _find(users: list[dict], name: str) -> dict:
    for u in users:
        if u["name"] == name:
            return u
    sys.exit(f"User '{name}' does not exist")

def _new_key(u: dict):
    api_key = secrets.token_urlsafe(32)
    u["key_sha256"] = _hash(api_key)
    print(f"API key for '{u['name']}' (save it now, it won't be shown again):\n\n    {api_key}\n")

def main():
    p   = argparse.ArgumentParser(description="Door API user management")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("add");     a.add_argument("name"); a.add_argument("--profile", choices=PROFILES, required=True)
    r = sub.add_parser("rotate");  r.add_argument("name")
    f = sub.add_parser("profile"); f.add_argument("name"); f.add_argument("profile", choices=PROFILES)
    d = sub.add_parser("disable"); d.add_argument("name")
    e = sub.add_parser("enable");  e.add_argument("name")
    x = sub.add_parser("remove");  x.add_argument("name")
    args = p.parse_args()

    users = _load()

    if args.cmd == "list":
        if not users:
            print("No users")
        for u in users:
            status = "active" if u.get("active", True) else "DISABLED"
            print(f"{u['name']:<20} {u['profile']:<8} {status}")
        return

    if args.cmd == "add":
        if not NAME_RE.match(args.name):
            sys.exit("Invalid name: use letters, digits, '_', '-' or '.' (max 40)")
        if any(u["name"] == args.name for u in users):
            sys.exit(f"User '{args.name}' already exists")
        u = {"name": args.name, "profile": args.profile, "active": True}
        _new_key(u)
        users.append(u)
    elif args.cmd == "rotate":
        _new_key(_find(users, args.name))
    elif args.cmd == "profile":
        _find(users, args.name)["profile"] = args.profile
    elif args.cmd == "disable":
        _find(users, args.name)["active"] = False
    elif args.cmd == "enable":
        _find(users, args.name)["active"] = True
    elif args.cmd == "remove":
        users.remove(_find(users, args.name))

    _save(users)
    print("users.toml updated. Restart the service to apply the changes (e.g. sudo systemctl restart door)")

if __name__ == "__main__":
    main()
