"""Environment configuration — mirrors the naming lib/server/env.ts uses on
the Next.js side, so the two services' .env files read the same at a glance.
"""

import os


def _required_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Shared secret with the Next.js app — see COLLECTIONS_SERVICE_SECRET in its
# .env.example. Authenticates both directions: it must be sent as
# `Authorization: Bearer <secret>` on every incoming /jobs request, and this
# service sends it right back on its callback.
COLLECTIONS_SERVICE_SECRET = os.environ.get("COLLECTIONS_SERVICE_SECRET", "")

# Cloudflare R2 (S3-compatible) — the exact same bucket and account the
# Next.js app itself uses (R2_ACCOUNT_ID / R2_ACCESS_KEY_ID /
# R2_SECRET_ACCESS_KEY / R2_BUCKET_NAME in its own .env). This service needs
# its own R2 API token (Object Read & Write on that one bucket) rather than
# reusing the app's — same credentials value works, but issuing a second
# token means either side can be rotated without touching the other.
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "")

# Upper bound on photos downloaded per board — a runaway board should not
# turn into an unbounded job. Matches MAX_IMAGES in
# app/api/collections/webhook/route.ts, which also caps what it will accept.
MAX_IMAGES = _required_int("MAX_IMAGES", 300)

# How long a single photo download may take before this service gives up on
# it and moves to the next one.
DOWNLOAD_TIMEOUT_SECONDS = _required_int("DOWNLOAD_TIMEOUT_SECONDS", 20)

# How long `gallery-dl` itself may run reading one board before this service
# gives up on the whole job — a huge or unusually slow board should time out
# rather than hang the job forever.
EXTRACTION_TIMEOUT_SECONDS = _required_int("EXTRACTION_TIMEOUT_SECONDS", 120)

PORT = _required_int("PORT", 8080)


def r2_configured() -> bool:
    return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME)
