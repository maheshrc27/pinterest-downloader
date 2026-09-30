# Pinterest board downloader

A small, standalone service that downloads every photo from a public
Pinterest board into the same Cloudflare R2 bucket the
[autoslides](../) Next.js app uses for its own photos, using
[gallery-dl](https://github.com/mikf/gallery-dl) to actually read the board.

It is **not** part of the Next.js app and does not share its build — deploy
it separately, anywhere that can run a small Python web service (Fly.io,
Render, Railway, Cloud Run, a plain VM with the included `Dockerfile`, ...).

## How it fits together

```
Next.js app                    this service
------------                   ------------
POST /api/collections   ---->  POST /jobs            (starts a download)
                                  |
                                  | gallery-dl reads the board,
                                  | downloads each photo,
                                  | uploads it to R2 at
                                  | assets/<ownerId>/<uuid>
                                  v
POST /api/collections/webhook <-- POST callbackUrl    (reports back)
```

Both requests carry `Authorization: Bearer <COLLECTIONS_SERVICE_SECRET>` —
the same value must be set on both services. Neither side trusts the other
any further than that: this service never sees an Appwrite session, and the
Next.js app never touches R2 credentials for someone else's photos.

**The object key convention is load-bearing.** The Next.js app's
`/api/assets` route only ever reads `assets/<the-signed-in-caller's-own-id>/<ref>`
— see `r2.py`'s `upload_asset`. Uploading anywhere else means the app can
never read the photo back.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in COLLECTIONS_SERVICE_SECRET + R2_*
set -a; source .env; set +a
uvicorn main:app --reload
```

Then point the Next.js app's `PINTEREST_DOWNLOADER_URL` at
`http://localhost:8000` (or wherever it's running) and give it the same
`COLLECTIONS_SERVICE_SECRET`. For a local Next.js dev server, this service
also needs to be able to reach it back at whatever `NEXT_PUBLIC_SITE_URL`
resolves to for the callback — a tunnel (cloudflared, ngrok) if either side
isn't reachable from the other directly.

You can sanity-check gallery-dl against a board on its own, outside this
service entirely:

```bash
gallery-dl --get-urls "https://www.pinterest.com/someone/some-board/"
```

## Deploying

The included `Dockerfile` runs `uvicorn main:app` on `$PORT`. Any platform
that can run an arbitrary container works:

```bash
docker build -t pinterest-downloader .
docker run -p 8080:8080 --env-file .env pinterest-downloader
```

Set the same env vars (`COLLECTIONS_SERVICE_SECRET`, `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`) on whatever
platform hosts it, then set `PINTEREST_DOWNLOADER_URL` on the Next.js app to
its public URL.

## How the download works

`downloader.py` runs `gallery-dl --get-urls --range 1-<MAX_IMAGES> <board
url>` as a subprocess — its own documented, stable CLI interface, rather
than its internal Python API (which has moved between versions). Each line
of output is a direct, downloadable image URL for one pin; a pin with more
than one usable URL prints its extra candidates on the following lines
prefixed with `| `, which are tried in order if the first one's request
fails. Every candidate is then downloaded with `requests` and uploaded to R2
directly — gallery-dl itself never writes anything to disk here.

Pinterest changes its site without notice, and gallery-dl tracks that
actively. If a board stops producing results:

1. Run the `gallery-dl --get-urls` command above on its own first — if that
   already returns nothing, it's a gallery-dl version issue, not a bug here.
   Bump the pin in `requirements.txt`.
2. If gallery-dl still sees the board but this service downloads nothing,
   the issue is in `downloader.py`'s parsing of its output, not the
   extraction itself.

## Limits

- At most `MAX_IMAGES` (default 300) photos per board — a board with more
  than that is truncated, not rejected.
- One job runs on a plain background thread per request, not a queue. Fine
  for the volume a single small app generates; swap in a real task queue
  (Celery, RQ, a cloud task queue) before this needs to handle many
  concurrent large boards.
- A failed or partially-failed download still reports back — see
  `downloader.run_job` — so a board never gets stuck showing "downloading"
  forever on the app side.
