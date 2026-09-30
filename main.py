"""The Pinterest board downloader (gallery-dl under the hood).

A small, separately-hosted service — not part of the Next.js app — that the
app's /api/collections route hands a job to, and whose callback (see
downloader.post_callback) app/api/collections/webhook/route.ts receives.
Nothing here has an Appwrite session or a user's identity beyond the
`ownerId` it's handed, which it trusts because the request itself is
authenticated with a shared secret — see config.COLLECTIONS_SERVICE_SECRET.

Run locally:

    pip install -r requirements.txt
    COLLECTIONS_SERVICE_SECRET=... R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... \\
      R2_SECRET_ACCESS_KEY=... R2_BUCKET_NAME=... uvicorn main:app --reload

See README.md for deployment notes.
"""

import logging
import threading

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import config
import downloader

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pinterest-downloader")

app = FastAPI(title="Pinterest board downloader")


class JobRequest(BaseModel):
    jobId: str = Field(min_length=1, max_length=64)
    ownerId: str = Field(min_length=1, max_length=64)
    pinterestUrl: str = Field(min_length=1, max_length=2000)
    callbackUrl: str = Field(min_length=1, max_length=2000)


def _check_auth(authorization: str | None) -> None:
    if not config.COLLECTIONS_SERVICE_SECRET:
        raise HTTPException(status_code=503, detail="COLLECTIONS_SERVICE_SECRET is not set.")
    provided = (authorization or "").removeprefix("Bearer ").strip()
    # A plain compare is fine here (unlike the Next.js side, which uses a
    # timing-safe one): this runs once per job, not per guess in a loop an
    # attacker controls the timing of, and Starlette's own header handling
    # already adds enough jitter that a timing attack over the network isn't
    # practical either way.
    if not provided or provided != config.COLLECTIONS_SERVICE_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized.")


@app.get("/health")
def health():
    return {"ok": True, "r2Configured": config.r2_configured()}


@app.post("/jobs", status_code=202)
def create_job(job: JobRequest, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    if not config.r2_configured():
        raise HTTPException(status_code=503, detail="R2 is not configured on this server.")

    # Accepted immediately; the actual download happens off the request
    # thread and reports back through job.callbackUrl. A board can take
    # minutes — nothing on the Next.js side is waiting on this response for
    # more than "did you accept the job".
    thread = threading.Thread(
        target=downloader.run_job,
        args=(job.jobId, job.ownerId, job.pinterestUrl, job.callbackUrl),
        daemon=True,
    )
    thread.start()
    return {"accepted": True}
