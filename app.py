from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import cloudinary
import cloudinary.api
import cloudinary.uploader
import cloudinary.utils
from flask import Flask, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_FILE = DATA_DIR / "data.json"

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
CLOUD_FOLDER = "limgp_moments"
TAG = "limgp_moments"
USE_CLOUDINARY = bool(os.environ.get("CLOUDINARY_URL"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

if not USE_CLOUDINARY:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _load_items() -> list[dict[str, Any]]:
    if USE_CLOUDINARY:
        try:
            resp = cloudinary.Search() \
                .expression(f"tags:{TAG}") \
                .with_field("context") \
                .sort_by("created_at", "desc") \
                .max_results(100) \
                .execute()
            resources = resp.get("resources", [])
        except Exception:
            app.logger.exception("Cloudinary search failed")
            resources = []

        if not resources:
            try:
                resp = cloudinary.api.resources(
                    resource_type="image",
                    type="upload",
                    prefix=f"{CLOUD_FOLDER}/",
                    tags=True,
                    context=True,
                    max_results=100,
                )
                resources = [
                    r for r in resp.get("resources", [])
                    if TAG in (r.get("tags") or [])
                ]
            except Exception:
                app.logger.exception("Cloudinary resources list failed")
                resources = []

        items = []
        for r in resources:
            context = r.get("context") or {}
            caption = context.get("caption", "")
            public_id = r.get("public_id") or ""
            image_url = r.get("secure_url") or r.get("url")
            if public_id:
                image_url, _ = cloudinary.utils.cloudinary_url(
                    public_id,
                    secure=True,
                    resource_type="image",
                    type="upload",
                    fetch_format="auto",
                )
            items.append(
                {
                    "id": r.get("asset_id") or r.get("public_id"),
                    "source": "cloud",
                    "public_id": public_id,
                    "image_url": image_url,
                    "caption": caption,
                    "created_at": r.get("created_at", ""),
                }
            )
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return items
    if not DATA_FILE.exists():
        return []
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save_items(items: list[dict[str, Any]]) -> None:
    if USE_CLOUDINARY:
        return
    DATA_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


@app.route("/", methods=["GET"])
def index():
    items = _load_items()
    msg = request.args.get("msg", "")
    level = request.args.get("level", "")
    debug = request.args.get("debug", "") == "1"
    return render_template("index.html", items=items, msg=msg, level=level, debug=debug)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename: str):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/upload", methods=["POST"])
def upload():
    caption = (request.form.get("caption") or "").strip()
    token = (request.form.get("token") or "").strip()
    required = os.environ.get("UPLOAD_TOKEN", "").strip()
    if required and token != required:
        return redirect(url_for("index", msg="上传口令不正确", level="error"))
    file = request.files.get("image")
    if not file or file.filename == "":
        return redirect(url_for("index", msg="请选择图片文件", level="error"))

    filename = secure_filename(file.filename)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        return redirect(url_for("index", msg="仅支持 JPG/PNG/GIF/WEBP 图片", level="error"))

    if USE_CLOUDINARY:
        try:
            cloudinary.uploader.upload(
                file,
                folder=CLOUD_FOLDER,
                tags=[TAG],
                context={"caption": caption},
            )
        except Exception:
            app.logger.exception("Cloudinary upload failed")
            return redirect(url_for("index", msg="上传失败，请稍后再试", level="error"))
    else:
        unique_name = f"{uuid.uuid4().hex}{ext}"
        save_path = UPLOAD_DIR / unique_name
        file.save(save_path)

        items = _load_items()
        items.append(
            {
                "id": uuid.uuid4().hex,
                "source": "local",
                "image": unique_name,
                "caption": caption,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        _save_items(items)

    return redirect(url_for("index", msg="上传成功", level="success"))


@app.errorhandler(413)
def file_too_large(_):
    return "文件过大，最大 10MB", 413


@app.route("/delete", methods=["POST"])
def delete():
    token = (request.form.get("token") or "").strip()
    required = os.environ.get("UPLOAD_TOKEN", "").strip()
    if required and token != required:
        return redirect(url_for("index", msg="管理口令不正确", level="error"))

    source = (request.form.get("source") or "").strip()
    if source == "cloud":
        public_id = (request.form.get("public_id") or "").strip()
        if not public_id:
            return redirect(url_for("index", msg="删除失败：缺少文件信息", level="error"))
        try:
            cloudinary.uploader.destroy(public_id, resource_type="image", type="upload")
        except Exception:
            app.logger.exception("Cloudinary delete failed")
            return redirect(url_for("index", msg="删除失败，请稍后再试", level="error"))
        return redirect(url_for("index", msg="已删除", level="success"))

    filename = (request.form.get("filename") or "").strip()
    if not filename:
        return redirect(url_for("index", msg="删除失败：缺少文件信息", level="error"))
    try:
        file_path = UPLOAD_DIR / filename
        if file_path.exists():
            file_path.unlink()
    except Exception:
        app.logger.exception("Local delete failed")
        return redirect(url_for("index", msg="删除失败，请稍后再试", level="error"))

    items = _load_items()
    items = [i for i in items if i.get("image") != filename]
    _save_items(items)
    return redirect(url_for("index", msg="已删除", level="success"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
