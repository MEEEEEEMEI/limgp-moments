from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_FILE = DATA_DIR / "data.json"

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _load_items() -> list[dict[str, Any]]:
    if not DATA_FILE.exists():
        return []
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save_items(items: list[dict[str, Any]]) -> None:
    DATA_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


@app.route("/", methods=["GET"])
def index():
    items = list(reversed(_load_items()))
    return render_template("index.html", items=items)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename: str):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/upload", methods=["POST"])
def upload():
    caption = (request.form.get("caption") or "").strip()
    token = (request.form.get("token") or "").strip()
    required = os.environ.get("UPLOAD_TOKEN", "").strip()
    if required and token != required:
        return redirect(url_for("index"))
    file = request.files.get("image")
    if not file or file.filename == "":
        return redirect(url_for("index"))

    filename = secure_filename(file.filename)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        return redirect(url_for("index"))

    unique_name = f"{uuid.uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / unique_name
    file.save(save_path)

    items = _load_items()
    items.append(
        {
            "id": uuid.uuid4().hex,
            "image": unique_name,
            "caption": caption,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save_items(items)

    return redirect(url_for("index"))


@app.errorhandler(413)
def file_too_large(_):
    return "文件过大，最大 10MB", 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
