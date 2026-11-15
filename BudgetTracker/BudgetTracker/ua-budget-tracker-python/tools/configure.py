#!/usr/bin/env python3
"""Create a new private .env without ever rotating an existing secret."""

import argparse, os, secrets
from pathlib import Path

p = argparse.ArgumentParser()
group = p.add_mutually_exclusive_group(required=True)
group.add_argument("--local", action="store_true")
group.add_argument("--production", action="store_true")
args = p.parse_args()
root = Path(__file__).resolve().parent.parent
dest = root / ".env"
if dest.exists():
    raise SystemExit(
        ".env already exists. Edit it manually; do not overwrite a working SECRET_KEY."
    )
text = (
    (root / ".env.example")
    .read_text(encoding="utf-8")
    .replace(
        "REPLACE_WITH_A_RANDOM_SECRET_AT_LEAST_32_CHARACTERS", secrets.token_hex(32)
    )
)
if args.local:
    text = text.replace("APP_ENV=production", "APP_ENV=development").replace(
        "SESSION_COOKIE_SECURE=1", "SESSION_COOKIE_SECURE=0"
    )
fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    stream.write(text)
print("Created .env with a new random secret. Keep it private and backed up.")
print("Next: python -m flask --app wsgi init-db")
print("Then: python -m flask --app wsgi create-admin")
