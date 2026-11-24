from datetime import timedelta
import os
from pathlib import Path
import re
import sys

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from markdown_it import MarkdownIt
from werkzeug.exceptions import HTTPException

from auth import SESSION_SECONDS, attach_auth
from content import Content, LANGUAGES
from database import Database
from media import MEDIA_REFERENCE, UPLOAD_NAME, Media
from publisher import BuildError, Publisher
from visitors import counter


REPO = Path(__file__).resolve().parents[2]
MESSAGES = {
    400: "요청 내용을 확인하세요.",
    401: "Google 로그인 후 이용하세요.",
    403: "이 요청에 접근할 수 없습니다.",
    404: "요청한 항목을 찾을 수 없습니다.",
    413: "파일 또는 요청이 너무 큽니다.",
    503: "Google 로그인이 아직 설정되지 않았습니다.",
}


def parsed_document(arguments):
    kind, number, lang = arguments.get("kind"), arguments.get("number"), arguments.get("lang")
    if isinstance(number, str) and number.isascii() and number.isdecimal() and len(number) <= 9:
        number = int(number)
    if (kind not in ("post", "about") or not isinstance(lang, str) or lang not in LANGUAGES or type(number) is not int
            or not 0 <= number <= 999_999_999 or (kind == "about" and number != 0)):
        abort(400)
    return kind, number, lang


def create_app(settings=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=os.getenv("AMIER_SESSION_KEY"),
        ADMIN_ORIGIN="https://amier.ge",
        GOOGLE_CLIENT_ID=os.getenv("AMIER_GOOGLE_CLIENT_ID", ""),
        STATE_DIR=os.getenv("AMIER_STATE_DIR", "/var/lib/amier-blog"),
        HUGO_BIN=os.getenv("AMIER_HUGO_BIN", "hugo"),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
        SESSION_COOKIE_NAME="__Host-amier-editor",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_REFRESH_EACH_REQUEST=False,
        PERMANENT_SESSION_LIFETIME=timedelta(seconds=SESSION_SECONDS),
    )
    app.config.update(settings or {})
    if not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("AMIER_SESSION_KEY must have at least 32 characters")
    state = Path(app.config["STATE_DIR"]).resolve()
    state.mkdir(parents=True, exist_ok=True)
    private = state / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    db = Database(private / "blog.sqlite3")
    media = Media(private / "media")
    publisher = Publisher(REPO, state, media, app.config["ADMIN_ORIGIN"], app.config["HUGO_BIN"])
    content = Content(REPO, db, publisher)
    app.extensions["content"] = content
    app.register_blueprint(counter(db))
    require_login = attach_auth(app, db)
    markdown = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    video_markup = re.compile(
        r'<video controls preload="metadata" src="/img/uploads/(' + UPLOAD_NAME + r')"></video>'
    )

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            response = error.get_response()
            response.data = app.json.dumps({"error": MESSAGES.get(error.code, error.description)})
            response.content_type = "application/json"
            return response
        return error

    @app.after_request
    def editor_headers(response):
        if request.path.startswith(("/api/editor/", "/editor/")):
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
                "object-src 'none'; form-action 'self'; "
                "script-src 'self' https://accounts.google.com; "
                "style-src 'self' https://accounts.google.com; "
                "connect-src 'self' https://accounts.google.com; "
                "frame-src https://accounts.google.com; img-src 'self' https: data:; "
                "media-src 'self';"
            )
        return response

    @app.get("/editor/")
    def editor():
        return send_from_directory(REPO / "src/editor", "index.html")

    @app.get("/editor/<asset>")
    def editor_asset(asset):
        if asset not in ("editor.css", "editor.js"):
            abort(404)
        return send_from_directory(REPO / "src/editor", asset)

    @app.get("/api/editor/posts")
    @require_login
    def posts():
        return jsonify(posts=content.catalog(), categories=content.categories)

    @app.get("/api/editor/document")
    @require_login
    def read_document():
        try:
            return jsonify(content.load(*parsed_document(request.args)))
        except LookupError:
            abort(404)

    @app.post("/api/editor/document/<action>")
    @require_login
    def update_document(action):
        if action not in ("save", "publish"):
            abort(404)
        fields = request.get_json(silent=True)
        if not isinstance(fields, dict):
            abort(400)
        try:
            return jsonify(content.update(*parsed_document(fields), fields, action == "publish"))
        except LookupError:
            abort(404)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except RuntimeError as error:
            return jsonify(error=str(error)), 409
        except BuildError:
            app.logger.exception("Hugo did not publish the document")
            return jsonify(error="빌드가 실패했습니다. 공개 사이트는 이전 버전 그대로입니다."), 422

    @app.post("/api/editor/upload")
    @require_login
    def upload():
        if "file" not in request.files:
            abort(400)
        try:
            return jsonify(media.upload(request.files["file"].stream)), 201
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/editor/media/<name>")
    @require_login
    def preview_media(name):
        try:
            path, mime = media.file(name)
        except LookupError:
            abort(404)
        return send_file(path, mimetype=mime, conditional=True)

    @app.post("/api/editor/preview")
    @require_login
    def preview():
        fields = request.get_json(silent=True)
        body = fields.get("body") if isinstance(fields, dict) else None
        if not isinstance(body, str) or len(body) > 1_000_000:
            abort(400)
        body = video_markup.sub(lambda m: "\n[업로드 영상](/img/uploads/" + m.group(1) + ")\n", body)
        rendered = markdown.render(body)
        rendered = MEDIA_REFERENCE.sub(lambda m: "/api/editor/media/" + m.group(1), rendered)
        rendered = re.sub(
            r'<a href="(/api/editor/media/[a-f0-9]{32}\.(?:mp4|webm))">업로드 영상</a>',
            r'<video controls preload="metadata" src="\1"></video>', rendered,
        )
        return jsonify(html=rendered)

    return app


if __name__ == "__main__":
    if sys.argv[1:] != ["build"]:
        raise SystemExit("Usage: python app.py build")
    create_app().extensions["content"].publish_initial()
