import json
import logging
import os
import random
import re
import time
from collections import OrderedDict
from threading import Lock

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from openai import OpenAI

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aimuseum")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

MET_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
MET_PAINTINGS_DEPT = 11  # European Paintings
MET_AMERICAN_DEPT = 21   # American Paintings
MET_ASIAN_DEPT = 6       # Asian Art (includes paintings)

UA = "Mozilla/5.0 (compatible; AIMuseumBot/1.0) Chrome/124"

CACHE_MAX = 512
AUDIO_CACHE_MAX = 64  # audio blobs are much larger than text, so cap tighter
SEARCH_CACHE_MAX = 64
SEARCH_CACHE_TTL = 60 * 30  # 30 min — Met search is stable
_painting_cache: "OrderedDict[str, dict]" = OrderedDict()
_interp_cache: "OrderedDict[str, str]" = OrderedDict()
_embellish_cache: "OrderedDict[str, dict]" = OrderedDict()
_audio_cache: "OrderedDict[str, bytes]" = OrderedDict()
_search_cache: "OrderedDict[str, tuple[float, list[int]]]" = OrderedDict()
_cache_lock = Lock()
_object_ids: list[int] = []
_object_ids_lock = Lock()

ELEVENLABS_VOICE_ID = "VJwFZoxTZo5aI0IowiXA"
ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"

# ─── Filters & quiz pools ────────────────────────────────────────────────────

CENTURIES = [
    "15th century", "16th century", "17th century", "18th century",
    "19th century", "20th century", "21st century",
]

# Met `dateBegin`/`dateEnd` ranges. Uses the colloquial museum convention
# where year 1500 falls into the 16th century (and 1499 into the 15th).
CENTURY_RANGES = {
    "15th century": (1400, 1499),
    "16th century": (1500, 1599),
    "17th century": (1600, 1699),
    "18th century": (1700, 1799),
    "19th century": (1800, 1899),
    "20th century": (1900, 1999),
    "21st century": (2000, 2099),
}

# Met's `geoLocation` filter expects place names. These are the most populous
# in the Open Access painting set.
CULTURES = [
    "France", "Italy", "Netherlands", "Spain", "United States",
    "Germany", "Britain", "Japan", "China", "Belgium",
]

# Used as decoy pool for the "guess the culture" quiz. The Met's `culture` and
# `artistNationality` fields use the adjective form ("French", "Italian"),
# which is what we'll see in normalized records — so the pool must match.
QUIZ_CULTURES = [
    "French", "Italian", "Dutch", "Spanish", "American",
    "German", "British", "Japanese", "Chinese", "Belgian",
    "Flemish", "Egyptian",
]

MEDIUMS = [
    "Oil on canvas", "Oil on wood", "Watercolor",
    "Tempera", "Pastel", "Gouache", "Ink",
]

# Movement labels used as Met `q=` keywords.
MOVEMENTS = [
    "Renaissance", "Baroque", "Romanticism", "Realism",
    "Impressionism", "Post-Impressionism", "Modern",
]

DECOY_ARTISTS = [
    "Claude Monet", "Vincent van Gogh", "Pablo Picasso", "Edgar Degas",
    "Pierre-Auguste Renoir", "Paul Cézanne", "Henri Matisse", "Édouard Manet",
    "Mary Cassatt", "John Singer Sargent", "James McNeill Whistler",
    "Rembrandt van Rijn", "Johannes Vermeer", "Caravaggio",
    "Diego Velázquez", "Francisco Goya", "Eugène Delacroix",
    "Gustav Klimt", "Egon Schiele", "Camille Pissarro",
    "Berthe Morisot", "Winslow Homer", "Thomas Eakins",
]


def _cache_set(cache: OrderedDict, key: str, value, max_size: int = CACHE_MAX):
    with _cache_lock:
        if key in cache:
            cache.move_to_end(key)
        cache[key] = value
        while len(cache) > max_size:
            cache.popitem(last=False)


def _cache_get(cache: OrderedDict, key: str):
    with _cache_lock:
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
    return None


_IDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "met_painting_ids.json")


def _load_painting_ids() -> list[int]:
    """Load pre-fetched Met painting object IDs from the bundled JSON file.

    Why: fetching the dept lists at cold start blew Vercel's function timeout.
    The IDs change rarely; refresh the file with scripts/refresh_met_ids.py.
    """
    global _object_ids
    with _object_ids_lock:
        if _object_ids:
            return _object_ids
        try:
            with open(_IDS_FILE, "r") as f:
                _object_ids = list(json.load(f))
            random.shuffle(_object_ids)
            log.info("Loaded %d painting IDs from %s", len(_object_ids), _IDS_FILE)
        except (OSError, ValueError) as e:
            log.error("Failed to load painting IDs: %s", e)
            _object_ids = []
        return _object_ids


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _derive_century(begin_year, end_year=None) -> str | None:
    """Label a year as e.g. '19th century'. 1500 → 16th, matching CENTURY_RANGES."""
    year = begin_year if begin_year and begin_year > 0 else end_year
    if not year or year <= 0:
        return None
    return f"{_ordinal(int(year) // 100 + 1)} century"


def _normalize_record(rec: dict) -> dict | None:
    image = rec.get("primaryImage") or rec.get("primaryImageSmall")
    if not image:
        return None
    if not rec.get("isPublicDomain", True):
        return None
    century = _derive_century(rec.get("objectBeginDate"), rec.get("objectEndDate"))
    return {
        "id": str(rec.get("objectID")),
        "title": rec.get("title") or "Untitled",
        "artist": rec.get("artistDisplayName") or "Unknown artist",
        "dated": rec.get("objectDate") or "Date unknown",
        "century": century,
        "culture": rec.get("culture") or rec.get("artistNationality"),
        "medium": rec.get("medium"),
        "classification": rec.get("classification"),
        "department": rec.get("department"),
        "period": rec.get("period"),
        "credit": rec.get("creditLine"),
        "image_url": image,
        "image_url_small": rec.get("primaryImageSmall") or image,
        "source_url": rec.get("objectURL"),
    }


def _fetch_met_object(object_id: int | str) -> dict | None:
    try:
        r = requests.get(
            f"{MET_BASE}/objects/{object_id}",
            headers={"User-Agent": UA},
            timeout=6,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("Met object %s fetch failed: %s", object_id, e)
        return None


def _search_filtered_ids(filters: dict) -> list[int]:
    """Hit the Met /search with filters and cache the result for 30 minutes.

    Why: filtered queries are too rare/niche to bake into the static IDs file,
    and the search response itself is reasonably small.
    """
    params = {"hasImages": "true"}
    medium = filters.get("medium") or "Paintings"
    params["medium"] = medium
    if filters.get("culture"):
        params["geoLocation"] = filters["culture"]
    if filters.get("century") and filters["century"] in CENTURY_RANGES:
        b, e = CENTURY_RANGES[filters["century"]]
        params["dateBegin"] = b
        params["dateEnd"] = e

    q = filters.get("movement") or "painting"
    cache_key = json.dumps({"q": q, **params}, sort_keys=True)

    with _cache_lock:
        cached = _search_cache.get(cache_key)
    if cached and time.time() - cached[0] < SEARCH_CACHE_TTL:
        return cached[1]

    qs = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    url = f"{MET_BASE}/search?{qs}&q={requests.utils.quote(q)}"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        r.raise_for_status()
    except (requests.RequestException, ValueError) as e:
        log.warning("Met filtered search failed: %s", e)
        return []
    ids = r.json().get("objectIDs") or []

    _cache_set(_search_cache, cache_key, (time.time(), ids), max_size=SEARCH_CACHE_MAX)
    return ids


def _filters_active(filters: dict | None) -> bool:
    return bool(filters) and any(filters.get(k) for k in ("movement", "century", "culture", "medium"))


def fetch_random_painting(filters: dict | None = None, retries: int = 8) -> dict | None:
    if _filters_active(filters):
        ids = _search_filtered_ids(filters)
        if not ids:
            return None
    else:
        ids = _load_painting_ids()
        if not ids:
            return None
    for _ in range(retries):
        candidate_id = random.choice(ids)
        rec = _fetch_met_object(candidate_id)
        if not rec:
            continue
        painting = _normalize_record(rec)
        if not painting:
            continue
        _cache_set(_painting_cache, painting["id"], painting)
        return painting
    return None


def fetch_painting_by_id(object_id: str) -> dict | None:
    cached = _cache_get(_painting_cache, object_id)
    if cached:
        return cached
    rec = _fetch_met_object(object_id)
    if not rec:
        return None
    painting = _normalize_record(rec)
    if not painting:
        return None
    _cache_set(_painting_cache, painting["id"], painting)
    return painting


def build_messages(painting: dict) -> list:
    title = painting["title"]
    artist = painting["artist"]
    dated = painting["dated"]
    medium = painting.get("medium") or ""
    medium_line = f" The medium is {medium}." if medium else ""

    system_prompt = (
        "You are an art historian writing for an intelligent general audience. "
        "You weave together what is visually present in the work with the era it was made, "
        "the artist's perspective, and the emotional charge of the piece. "
        "Be vivid but never flowery. Avoid clichés. Avoid listing features mechanically. "
        "Write a single flowing paragraph of 4 to 6 sentences."
    )
    user_prompt = (
        f'Look closely at "{title}" by {artist} ({dated}).{medium_line} '
        "First describe what is actually in the image — composition, light, gesture, mood — "
        "then carry that into the historical and emotional context. One paragraph."
    )

    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": painting["image_url"]}},
            ],
        },
    ]


def stream_interpretation(painting: dict):
    cached = _cache_get(_interp_cache, painting["id"])
    if cached:
        for chunk in _chunk_text(cached, size=20):
            yield _sse("token", {"text": chunk})
        yield _sse("done", {"text": cached})
        return

    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=build_messages(painting),
            max_tokens=400,
            stream=True,
        )
    except Exception as e:
        log.exception("OpenAI request failed")
        yield _sse("error", {"message": "The interpretation couldn't be generated."})
        return

    full = []
    try:
        for event in completion:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                full.append(piece)
                yield _sse("token", {"text": piece})
    except Exception:
        log.exception("OpenAI stream interrupted")
        yield _sse("error", {"message": "The connection to the model dropped."})
        return

    text = "".join(full).strip()
    if text:
        _cache_set(_interp_cache, painting["id"], text)
    yield _sse("done", {"text": text})


def _chunk_text(text: str, size: int = 20):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.route("/")
def landing_page():
    return render_template("landing.html")


@app.route("/app")
def museum():
    object_id = request.args.get("id")
    return render_template(
        "index.html",
        initial_id=object_id,
        filter_options={
            "movements": MOVEMENTS,
            "centuries": CENTURIES,
            "cultures": CULTURES,
            "mediums": MEDIUMS,
        },
    )


@app.route("/favorites")
def favorites():
    return render_template("favorites.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/quiz")
def quiz_page():
    return render_template("quiz.html")


def _filters_from_request() -> dict:
    return {
        "movement": (request.args.get("movement") or "").strip() or None,
        "century": (request.args.get("century") or "").strip() or None,
        "culture": (request.args.get("culture") or "").strip() or None,
        "medium": (request.args.get("medium") or "").strip() or None,
    }


@app.route("/api/painting/random")
def api_random_painting():
    filters = _filters_from_request()
    painting = fetch_random_painting(filters)
    if not painting:
        msg = "No artwork matches those filters." if _filters_active(filters) else "Could not fetch a painting right now."
        return jsonify({"error": msg}), 404 if _filters_active(filters) else 502
    return jsonify(painting)


@app.route("/api/painting/<object_id>")
def api_painting_by_id(object_id):
    painting = fetch_painting_by_id(object_id)
    if not painting:
        return jsonify({"error": "Artwork not found."}), 404
    return jsonify(painting)


@app.route("/api/painting/<object_id>/embellish")
def api_embellish(object_id):
    """After the streamed interpretation lands, distill it into a pull-quote
    and a list of evocative phrases to highlight inside the prose.

    Cached per-painting. Returns 409 if the interpretation isn't ready yet,
    matching the audio endpoint's contract.
    """
    cached = _cache_get(_embellish_cache, object_id)
    if cached:
        return jsonify(cached)

    text = _cache_get(_interp_cache, object_id)
    if not text:
        return jsonify({"error": "Interpretation not ready yet."}), 409

    schema_prompt = (
        "Read the interpretation below. Reply with ONLY a JSON object, exactly:\n"
        "{\n"
        '  "pull_quote": "ONE beautiful sentence (max 16 words) distilled from the spirit of this interpretation — something a viewer could carry with them. Original phrasing is fine.",\n'
        '  "highlights": ["3–5 short phrases (1–4 words each), copied EXACTLY (case-sensitive) from the interpretation, that are the most evocative. They will be visually emphasized in the running text."]\n'
        "}\n\n"
        "Interpretation:\n" + text
    )
    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a careful editor. You reply with valid JSON only.",
                },
                {"role": "user", "content": schema_prompt},
            ],
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        data = json.loads(completion.choices[0].message.content.strip())
    except Exception as e:
        log.warning("Embellish failed: %s", e)
        return jsonify({"error": "Couldn't distill this interpretation."}), 502

    payload = {
        "pull_quote": (data.get("pull_quote") or "").strip().strip('"').strip("'"),
        "highlights": [h.strip() for h in (data.get("highlights") or []) if h and h.strip()],
    }
    _cache_set(_embellish_cache, object_id, payload)
    return jsonify(payload)


@app.route("/api/quiz/new")
def api_quiz_new():
    """One quiz question. mode = century | culture | artist."""
    mode = request.args.get("mode", "century")

    require_field = {"century": "century", "culture": "culture", "artist": "artist"}.get(mode)
    painting = None
    for _ in range(6):
        candidate = fetch_random_painting()
        if not candidate:
            continue
        value = candidate.get(require_field) if require_field else None
        if not value:
            continue
        if mode == "artist" and value.lower().startswith("unknown"):
            continue
        painting = candidate
        break

    if not painting:
        return jsonify({"error": "Could not load a quiz artwork. Try again."}), 503

    if mode == "century":
        correct = painting["century"]
        pool = list(CENTURIES)
    elif mode == "culture":
        correct = painting["culture"]
        pool = list(QUIZ_CULTURES)
    else:
        correct = painting["artist"]
        pool = list(DECOY_ARTISTS)

    if correct and correct not in pool:
        pool.append(correct)
    wrong = [p for p in pool if p != correct]
    options = random.sample(wrong, min(3, len(wrong)))
    options.append(correct)
    random.shuffle(options)

    return jsonify({
        "id": painting["id"],
        "image_url": painting["image_url"],
        "title": painting["title"],
        "artist": painting["artist"],
        "dated": painting["dated"],
        "century": painting["century"],
        "culture": painting["culture"],
        "source_url": painting.get("source_url"),
        "options": options,
        "correct": correct,
        "mode": mode,
    })


@app.route("/api/painting/<object_id>/audio")
def api_audio(object_id):
    cached_audio = _cache_get(_audio_cache, object_id)
    if cached_audio is not None:
        return Response(cached_audio, mimetype="audio/mpeg")

    text = _cache_get(_interp_cache, object_id)
    if not text:
        return jsonify({"error": "Interpretation not ready yet."}), 409

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        log.error("ELEVENLABS_API_KEY is not set")
        return jsonify({"error": "Audio service not configured."}), 503

    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": ELEVENLABS_MODEL_ID,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.0,
                    "use_speaker_boost": True,
                },
            },
            timeout=60,
        )
    except requests.RequestException as e:
        log.warning("ElevenLabs request failed: %s", e)
        return jsonify({"error": "Couldn't reach the audio service."}), 502

    if r.status_code != 200:
        log.warning("ElevenLabs returned %s: %s", r.status_code, r.text[:300])
        return jsonify({"error": "Audio generation failed."}), 502

    audio_bytes = r.content
    _cache_set(_audio_cache, object_id, audio_bytes, max_size=AUDIO_CACHE_MAX)
    return Response(audio_bytes, mimetype="audio/mpeg")


@app.route("/api/painting/<object_id>/interpretation")
def api_interpretation(object_id):
    painting = fetch_painting_by_id(object_id)
    if not painting:
        return jsonify({"error": "Artwork not found."}), 404

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(
        stream_with_context(stream_interpretation(painting)),
        headers=headers,
    )


@app.after_request
def add_caching_headers(response):
    if request.path.startswith("/static"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.path.startswith("/api/painting") and "interpretation" not in request.path:
        response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
