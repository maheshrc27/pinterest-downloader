"""The actual board download — gallery-dl for extraction, requests for the
bytes, r2.py for storage.

gallery-dl (https://github.com/mikf/gallery-dl) is a purpose-built image/
gallery downloader with its own Pinterest extractor covering boards, users,
sections and single pins alike, so nothing here needs to special-case which
kind of URL it was handed — gallery-dl figures that out itself.

Run as a subprocess (`gallery-dl -g`) rather than through its Python API:
that API is undocumented and has moved between versions, where the `-g`
("print the URLs it would download, one per line") CLI flag is gallery-dl's
own stable, documented interface. A pin with more than one usable URL (say,
a re-encoded fallback) prints its extra candidates on the following lines,
each prefixed with "| " — those are tried in order if the primary URL's
request fails, rather than being separate pins.
"""

import logging
import subprocess
import time

import requests

import config
import r2

log = logging.getLogger("pinterest-downloader")

CONTENT_TYPE_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


class ExtractionError(Exception):
    """gallery-dl itself failed or refused the URL — see its stderr."""


def _image_ext(url: str) -> str | None:
    """The URL's image extension, or None for anything that isn't a still
    (audio, video, ...) — those are skipped rather than stored as photos."""
    ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
    return ext if ext in CONTENT_TYPE_BY_EXT else None


def extract_board_items(board_url: str, max_images: int) -> list[list[str]]:
    """One entry per pin gallery-dl finds, each a list of candidate URLs
    (primary first, any fallbacks after) — nothing is downloaded yet."""
    args = [
        "gallery-dl",
        "--get-urls",
        "--range",
        f"1-{max_images}",
        board_url,
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=config.EXTRACTION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise ExtractionError(f"gallery-dl timed out reading the board: {e}") from e

    if result.returncode != 0 and not result.stdout.strip():
        raise ExtractionError((result.stderr or "gallery-dl found nothing on that board.").strip()[:500])

    items: list[list[str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("|"):
            # A fallback candidate for the pin just above, not a new pin.
            if items:
                items[-1].append(line.lstrip("|").strip())
        else:
            items.append([line])
    return items


def _download_first_that_works(candidates: list[str]) -> tuple[bytes, str] | None:
    """Tries each candidate URL for one pin in order, returning the first
    that actually downloads. Most pins have exactly one candidate.

    A video pin gallery-dl can't resolve itself comes through prefixed
    `ytdl:` — its own signal to hand the URL to yt-dlp instead of fetching it
    directly. This service only wants stills for a background-photo pool, so
    those are skipped outright rather than handed to `requests`, which has no
    idea what to do with a non-http(s) scheme anyway.
    """
    for url in candidates:
        if not url.startswith(("http://", "https://")):
            continue
        ext = _image_ext(url)
        if not ext:
            continue
        try:
            response = requests.get(url, timeout=config.DOWNLOAD_TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as e:
            log.warning("Candidate failed (%s): %s", url, e)
            continue
        return response.content, ext
    return None


def download_board(owner_id: str, board_url: str) -> list[str]:
    """Downloads every photo gallery-dl can find on the board straight into
    R2, returning their `r2:<ref>` pointers. Best-effort per pin: one bad pin
    is skipped, not fatal."""
    items = extract_board_items(board_url, config.MAX_IMAGES)
    refs: list[str] = []

    for candidates in items:
        if len(refs) >= config.MAX_IMAGES:
            break

        downloaded = _download_first_that_works(candidates)
        if not downloaded:
            continue
        body, ext = downloaded

        content_type = CONTENT_TYPE_BY_EXT.get(ext, "image/jpeg")
        try:
            ref = r2.upload_asset(owner_id, body, content_type)
        except Exception as e:  # noqa: BLE001 — one failed upload shouldn't sink the job
            log.warning("Could not upload %s to R2: %s", candidates[0], e)
            continue

        refs.append(ref)

    return refs


def post_callback(callback_url: str, job_id: str, **fields) -> None:
    body = {"jobId": job_id, **fields}
    for attempt in range(3):
        try:
            resp = requests.post(
                callback_url,
                json=body,
                headers={"Authorization": f"Bearer {config.COLLECTIONS_SERVICE_SECRET}"},
                timeout=15,
            )
            if resp.ok:
                return
            log.error("Callback rejected (%s): %s", resp.status_code, resp.text[:200])
        except requests.RequestException as e:
            log.error("Callback attempt %d failed: %s", attempt + 1, e)
        time.sleep(2**attempt)


def run_job(job_id: str, owner_id: str, pinterest_url: str, callback_url: str) -> None:
    """The whole pipeline for one board, run in the background — see main.py's
    /jobs handler, which returns as soon as this is scheduled rather than
    waiting for it."""
    post_callback(callback_url, job_id, status="downloading")
    try:
        refs = download_board(owner_id, pinterest_url)
    except Exception as e:  # noqa: BLE001 — must still report failure, not just crash silently
        log.exception("Job %s failed", job_id)
        post_callback(callback_url, job_id, status="failed", error=str(e)[:500])
        return

    if not refs:
        post_callback(
            callback_url,
            job_id,
            status="failed",
            error="Could not find any downloadable photos on that board.",
        )
        return

    post_callback(callback_url, job_id, status="ready", imageRefs=refs)
