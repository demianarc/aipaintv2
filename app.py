import json
import logging
import os
import random
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
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

MET_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
MET_PAINTINGS_DEPT = 11  # European Paintings
MET_AMERICAN_DEPT = 21   # American Paintings
MET_ASIAN_DEPT = 6       # Asian Art (includes paintings)

UA = "Mozilla/5.0 (compatible; AIMuseumBot/1.0) Chrome/124"

CACHE_MAX = 512
_painting_cache: "OrderedDict[str, dict]" = OrderedDict()
_interp_cache: "OrderedDict[str, str]" = OrderedDict()
_cache_lock = Lock()
_object_ids: list[int] = []
_object_ids_lock = Lock()


def _cache_set(cache: OrderedDict, key: str, value):
    with _cache_lock:
        if key in cache:
            cache.move_to_end(key)
        cache[key] = value
        while len(cache) > CACHE_MAX:
            cache.popitem(last=False)


def _cache_get(cache: OrderedDict, key: str):
    with _cache_lock:
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
    return None


def _load_painting_ids() -> list[int]:
    """Pull and merge painting object-IDs from a few Met departments."""
    global _object_ids
    with _object_ids_lock:
        if _object_ids:
            return _object_ids
        merged: set[int] = set()
        for dept in (MET_PAINTINGS_DEPT, MET_AMERICAN_DEPT):
            try:
                r = requests.get(
                    f"{MET_BASE}/objects",
                    params={"departmentIds": dept},
                    headers={"User-Agent": UA},
                    timeout=15,
                )
                r.raise_for_status()
                ids = r.json().get("objectIDs") or []
                merged.update(ids)
            except (requests.RequestException, ValueError) as e:
                log.warning("Met department %s list failed: %s", dept, e)
        _object_ids = list(merged)
        random.shuffle(_object_ids)
        log.info("Loaded %d painting IDs from the Met", len(_object_ids))
        return _object_ids


def _normalize_record(rec: dict) -> dict | None:
    image = rec.get("primaryImage") or rec.get("primaryImageSmall")
    if not image:
        return None
    if not rec.get("isPublicDomain", True):
        return None
    return {
        "id": str(rec.get("objectID")),
        "title": rec.get("title") or "Untitled",
        "artist": rec.get("artistDisplayName") or "Unknown artist",
        "dated": rec.get("objectDate") or "Date unknown",
        "century": None,
        "culture": rec.get("culture") or rec.get("artistNationality"),
        "medium": rec.get("medium"),
        "classification": rec.get("classification"),
        "department": rec.get("department"),
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
            timeout=15,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("Met object %s fetch failed: %s", object_id, e)
        return None


def fetch_random_painting(retries: int = 8) -> dict | None:
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
    return render_template("index.html", initial_id=object_id)


@app.route("/favorites")
def favorites():
    return render_template("favorites.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/api/painting/random")
def api_random_painting():
    painting = fetch_random_painting()
    if not painting:
        return jsonify({"error": "Could not fetch a painting right now."}), 502
    return jsonify(painting)


@app.route("/api/painting/<object_id>")
def api_painting_by_id(object_id):
    painting = fetch_painting_by_id(object_id)
    if not painting:
        return jsonify({"error": "Artwork not found."}), 404
    return jsonify(painting)


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
