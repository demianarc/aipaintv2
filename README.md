# The AI Museum

A small Flask app that pulls a random public-domain painting from **The Met's Open Access collection** and asks a multimodal OpenAI model to interpret it like an art historian — image + context, streamed live to the browser.

- **Stack:** Python 3.11 · Flask · vanilla JS · Jinja templates · OpenAI vision · Met Museum API
- **Deploy target:** Vercel (`@vercel/python`) — also runs locally with `python app.py`
- **No database.** Favorites live in the browser's `localStorage`. The server keeps two in-memory LRU caches.

---

## How it works (end to end)

```
   ┌────────────┐      1. GET /api/painting/random        ┌──────────────────┐
   │  Browser   │ ───────────────────────────────────────▶│  Flask (app.py)  │
   │ (app.js)   │                                          └──────┬───────────┘
   │            │      2. JSON {id, title, artist, image}        │
   │            │ ◀─────────────────────────────────────────────  │
   │            │                                                 │ HTTP
   │            │      3. GET /api/painting/<id>/interpretation   │
   │            │ ───────────────────────────────────────▶  ┌─────▼─────────┐
   │            │      4. SSE stream: token, token, …, done │ Met Museum API│
   │            │ ◀──────────────────────────────────────── │ + OpenAI API  │
   │            │                                            └───────────────┘
   │            │   5. ❤︎ favourite → localStorage only
   └────────────┘
```

1. User hits `/app`. The page renders a skeleton and the JS calls `/api/painting/random`.
2. Flask picks a random object ID from a pre-loaded list of Met painting IDs, fetches its full record, normalizes it, and returns JSON.
3. Once the image and metadata are rendered, the JS opens an **EventSource-style streaming fetch** at `/api/painting/<id>/interpretation`.
4. Flask sends the painting's image URL + metadata to the OpenAI chat-completions API in **streaming mode** and forwards each token to the browser as a Server-Sent Event. The completed text is cached server-side keyed by painting ID.
5. The browser appends tokens to the DOM as they arrive. "Save" writes the painting to `localStorage` — there is no user account.

While the user reads, the JS pre-fetches the next random painting so "Next artwork" feels instant.

---

## Backend — `app.py`

Single-file Flask app. Three responsibilities:

### 1. Met Museum integration
- On first request, pulls all object IDs from departments **11 (European Paintings)** and **21 (American Paintings)** via `GET {MET_BASE}/objects?departmentIds=…`, merges and shuffles them. Stored in module-level `_object_ids` behind a `Lock`.
- `fetch_random_painting()` picks an ID, calls `GET /objects/{id}`, and retries up to 8 times if the record has no image or isn't public domain.
- `_normalize_record()` converts the Met's verbose response into a flat shape used everywhere downstream:
  ```python
  {id, title, artist, dated, century, culture, medium,
   classification, department, credit, image_url,
   image_url_small, source_url}
  ```

### 2. OpenAI interpretation (streaming)
- `build_messages(painting)` builds a system + user prompt and attaches the image URL via the OpenAI vision schema (`{"type": "image_url", "image_url": {"url": …}}`).
- `stream_interpretation(painting)` is a Python generator. It calls `client.chat.completions.create(..., stream=True)` and yields each delta as an SSE frame:
  ```
  event: token
  data: {"text": "…"}
  ```
  When done it yields `event: done` with the full text and writes it to `_interp_cache`.
- If a painting has already been interpreted, the cached text is replayed in 20-char chunks so the UI behaves identically on a cache hit.
- Model is `OPENAI_MODEL` env var, default `gpt-4o`.

### 3. Caches
Two thread-safe `OrderedDict` LRU caches, capped at `CACHE_MAX = 512`:
- `_painting_cache` — normalized painting records keyed by Met objectID
- `_interp_cache` — finished interpretation text keyed by Met objectID

Lock: `_cache_lock` around every read/write. The painting-ID list has its own `_object_ids_lock`.

### Routes

| Method | Path | Returns |
|---|---|---|
| GET | `/` | `landing.html` |
| GET | `/app` | `index.html` (museum view; optional `?id=` deep link) |
| GET | `/favorites` | `favorites.html` |
| GET | `/about` | `about.html` |
| GET | `/api/painting/random` | JSON painting record |
| GET | `/api/painting/<id>` | JSON painting record (or 404) |
| GET | `/api/painting/<id>/interpretation` | `text/event-stream` (SSE) |

`@app.after_request` sets `Cache-Control: public, max-age=31536000, immutable` for `/static/*` and `no-store` for painting API responses (interpretation stream is left alone).

---

## Frontend — `static/js/app.js`

Vanilla JS, no build step. One file, several small modules attached to `DOMContentLoaded`:

| Module | Purpose |
|---|---|
| `Theme` | Light/dark toggle, persisted to `localStorage["theme"]`. Sets `data-theme` on `<html>`. |
| `Toast` | Bottom toast notifications with optional action button (used for "Undo"). |
| `Favorites` | Wraps `localStorage["aim:favorites:v2"]`. CRUD + `has(id)`. |
| `Modal` | Click the artwork image → fullscreen viewer. ESC to close. |
| `Museum` | The artwork view on `/app`. See below. |
| `FavoritesPage` | Renders the saved-artwork grid on `/favorites`. |

### `Museum` — the core flow

1. `init()` reads `window.__INITIAL_ID__` (set in `index.html` from the optional `?id=` query) — if present, calls `loadById(id)`; otherwise `loadRandom()`.
2. `fetchAndRender(url)` → `render(painting)` paints title/byline/tags, preloads the image off-DOM, then swaps it in.
3. `streamInterpretation(id)` opens a streaming `fetch` and parses SSE manually:
   ```js
   const events = chunk.split("\n\n");           // SSE frame separator
   for (const evt of events) {
     const { event, data } = parseSse(evt);
     if (event === "token") buffer += data.text; // append to text node
     if (event === "done")  cursor.remove();
   }
   ```
   The text is appended as a single text-node mutation per token (no `innerHTML`, no XSS surface). A blinking `.cursor` element is shown until `done`.
4. `prefetchNext()` fires another `/api/painting/random` plus a hidden `Image()` to warm the browser cache for the next click.
5. `abortPreviousStream()` is called whenever a new painting loads — the previous fetch is `AbortController`-cancelled so dropped tokens don't leak into the next view.

Keyboard: `n` or `→` = next painting, `f` = favorite.

### Favorites lifecycle
- Saving stores a snapshot of the painting (id, title, artist, image, interpretation, saved_at).
- If the interpretation finishes after saving, the favorite record is updated in place so the cached text travels with it.
- The favorites page renders cards from `localStorage` only — clicking a card deep-links to `/app?id=<id>`. Removing shows an "Undo" toast for 5 s.

---

## Templates

```
templates/
  _base.html      shared shell: nav, theme toggle, modal, toast container, JS+CSS includes
  landing.html    /        marketing splash
  index.html      /app     museum view (skeleton + data-* hooks for Museum module)
  favorites.html  /favorites    empty container, JS fills it
  about.html      /about   prose
```

`_base.html` loads Google Fonts (Fraunces + Inter) and the single `static/css/app.css`.

---

## Local dev

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # if present; otherwise create it
echo "OPENAI_API_KEY=sk-..." >> .env

python app.py          # http://localhost:5001
```

Optional env vars:
- `OPENAI_API_KEY` *(required)*
- `OPENAI_MODEL` — default `gpt-4o`
- `PORT` — default `5001`
- `FLASK_DEBUG=1` — enable Flask debug

First random-painting request takes a few seconds because it warms `_object_ids` from the Met. Subsequent requests are fast.

---

## Deployment (Vercel)

`vercel.json` routes everything except `/static/*` to `app.py` via `@vercel/python`:
```json
{
  "version": 2,
  "builds":  [{ "src": "app.py", "use": "@vercel/python" }],
  "routes":  [
    { "src": "/static/(.*)", "dest": "/static/$1" },
    { "src": "/(.*)",        "dest": "app.py" }
  ]
}
```

Set `OPENAI_API_KEY` (and optionally `OPENAI_MODEL`) in the Vercel project's env vars. `runtime.txt` pins Python 3.11.

> **Note on serverless caches:** the in-memory LRU caches reset on every cold start, so on Vercel the Met-ID list and interpretation cache effectively live per-instance. That's fine for this app — interpretations regenerate cheaply — but worth knowing if you fork it.

A `gunicorn` entry is in `requirements.txt` for traditional hosts; run with `gunicorn app:app`.

---

## File map

```
.
├── app.py                  # Flask app — routes, Met fetching, OpenAI streaming, caches
├── requirements.txt        # Flask, requests, openai, python-dotenv, gunicorn
├── runtime.txt             # python-3.11 (Vercel)
├── vercel.json             # serverless routing
├── templates/
│   ├── _base.html
│   ├── landing.html
│   ├── index.html
│   ├── favorites.html
│   └── about.html
└── static/
    ├── favicon.png
    ├── css/app.css         # all styles, theme tokens via [data-theme]
    └── js/app.js           # Theme, Toast, Favorites, Modal, Museum, FavoritesPage
```

---

## Credits

Artworks from [The Met's Open Access collection](https://www.metmuseum.org/art/collection). Interpretations generated by OpenAI. Built by Dylan.
