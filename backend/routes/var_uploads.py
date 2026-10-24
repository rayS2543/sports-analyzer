"""Clips the user supplies themselves (their own recording, or footage they have the right to use).

The user's file is the only input: nothing is fetched from a URL here, and ESPN's CDN check for downloads stays
as it is. A stored clip lives where an ESPN clip would (var_data/<id>/video.mp4) under an id that cannot clash with
ESPN's, so analysis, windows and the video route work on it unchanged."""
import hashlib
import json
import os
import re
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from routes.var_analysis import _out

var_uploads_bp = Blueprint("var_uploads", __name__)
MAX_UPLOAD_BYTES = 1 << 30  # 1 GiB: a full-match clip is far over what a 10 s window needs
UPLOAD_META = "upload.json"
UPLOAD_ID = re.compile(r"9\d{10}")  # 11 digits starting with 9; ESPN's ids are 8 digits


def upload_meta(clip_id):
    """The metadata of an uploaded clip, or None for anything else (an ESPN clip, an unknown id)."""
    if not UPLOAD_ID.fullmatch(clip_id or ""):
        return None
    path = _out(clip_id) / UPLOAD_META
    try:
        return json.loads(path.read_text()) if path.is_file() and (_out(clip_id) / "video.mp4").is_file() else None
    except (OSError, ValueError):
        return None


def _title(text, filename):
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", text or "").strip()[:120]
    return cleaned or re.sub(r"[\x00-\x1f\x7f]", " ", Path(filename or "clip").stem).strip()[:120] or "Uploaded clip"


def _store(path, sha, total, filename, title):
    """Move a checked MP4 (already hashed) into the clip store: (meta, None), or (None, (message, http status))."""
    clip_id = "9" + str(int(sha[:12], 16) % 10**10).zfill(10)
    existing = upload_meta(clip_id)
    if existing and existing.get("sha256") != sha:
        return None, ("Another uploaded clip already has this id; rename and try again", 409)
    if existing:
        return existing, None
    _out(clip_id).mkdir(parents=True, exist_ok=True)
    os.replace(path, _out(clip_id) / "video.mp4")
    meta = {"id": clip_id, "title": title, "filename": Path(filename).name[:200], "sha256": sha, "bytes": total,
            "uploaded_at": int(time.time()), "source": "upload"}
    (_out(clip_id) / UPLOAD_META).write_text(json.dumps(meta))
    return meta, None


def _import_inbox():
    """Take MP4s the user dropped into var_data/inbox into the clip store (moved, so nothing is kept twice)."""
    inbox = _out("inbox")
    if not inbox.is_dir():
        return
    for path in sorted(inbox.glob("*.mp4")):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            size = path.stat().st_size
            if not 0 < size <= MAX_UPLOAD_BYTES:
                continue
            with open(path, "rb") as f:
                if f.read(8)[4:8] != b"ftyp":
                    continue
                f.seek(0)
                digest = hashlib.sha256()
                while chunk := f.read(1 << 20):
                    digest.update(chunk)
            _, error = _store(path, digest.hexdigest(), size, path.name, _title(None, path.name))
            if not error:
                path.unlink(missing_ok=True)  # a file already stored (seen before) is left here until now: drop the duplicate
        except OSError:
            continue


@var_uploads_bp.post("/var/upload")
def upload():
    file = request.files.get("file")
    if not file or not (file.filename or "").lower().endswith(".mp4"):
        return jsonify(error="Attach an .mp4 file as 'file'"), 400
    if request.content_length and request.content_length > MAX_UPLOAD_BYTES + (1 << 20):
        return jsonify(error="The video is larger than 1 GB"), 413
    root = _out("uploads-tmp")
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"{os.getpid()}-{time.time_ns()}.part"
    digest, total = hashlib.sha256(), 0
    try:
        with open(tmp, "wb") as out:
            while chunk := file.stream.read(1 << 20):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    return jsonify(error="The video is larger than 1 GB"), 413
                if total == len(chunk) and chunk[4:8] != b"ftyp":
                    return jsonify(error="That file is not an MP4 video"), 400
                digest.update(chunk)
                out.write(chunk)
        if not total:
            return jsonify(error="The file is empty"), 400
        meta, error = _store(tmp, digest.hexdigest(), total, file.filename, _title(request.form.get("title"), file.filename))
        return (jsonify(error=error[0]), error[1]) if error else (jsonify(clip=meta), 201)
    finally:
        tmp.unlink(missing_ok=True)


@var_uploads_bp.get("/var/uploads")
def uploads():
    """Uploaded clips, newest first; first takes in anything dropped into var_data/inbox."""
    _import_inbox()
    base = _out("")
    found = [m for d in base.iterdir() if d.is_dir() and (m := upload_meta(d.name))] if base.is_dir() else []
    found.sort(key=lambda m: m.get("uploaded_at", 0), reverse=True)
    return jsonify(clips=[{k: m[k] for k in ("id", "title", "filename", "bytes", "uploaded_at")} for m in found])
