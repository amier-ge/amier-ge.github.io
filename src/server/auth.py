from contextlib import closing
from functools import wraps
from secrets import compare_digest, token_urlsafe
import time

from cachecontrol import CacheControl
from flask import abort, jsonify, request, session
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import id_token
import requests


OWNER = "amierge.df@gmail.com"
SESSION_SECONDS = 8 * 60 * 60


class GoogleTransport(Request):
    def __call__(self, url, method="GET", body=None, headers=None, **kwargs):
        kwargs.pop("timeout", None)
        return super().__call__(url, method, body, headers, timeout=8, **kwargs)


def attach_auth(app, db):
    transport = GoogleTransport(CacheControl(requests.Session()))

    def current_session():
        login_id = session.get("login_id")
        if not login_id:
            return False
        with closing(db.connect()) as conn:
            return conn.execute(
                "SELECT 1 FROM sessions WHERE id = ? AND expires > ?", (login_id, int(time.time()))
            ).fetchone() is not None

    def same_origin():
        if request.headers.get("Origin") != app.config["ADMIN_ORIGIN"]:
            abort(403)

    def require_login(handler):
        @wraps(handler)
        def guarded(*args, **kwargs):
            if not current_session():
                abort(401)
            if request.method not in {"GET", "HEAD"}:
                same_origin()
                csrf = session.get("csrf", "")
                received = request.headers.get("X-CSRF-Token", "")
                if not csrf or not received.isascii() or not compare_digest(received, csrf):
                    abort(403)
            return handler(*args, **kwargs)

        return guarded

    @app.get("/api/editor/session")
    def status():
        client_id = app.config["GOOGLE_CLIENT_ID"]
        if current_session():
            return jsonify(signedIn=True, csrf=session["csrf"], email=OWNER)
        if not client_id:
            return jsonify(signedIn=False, configured=False)
        nonce = session.get("nonce")
        issued = session.get("nonce_time", 0)
        if not nonce or int(time.time()) - issued >= 600:
            session.clear()
            session["nonce"] = nonce = token_urlsafe(32)
            session["nonce_time"] = int(time.time())
        return jsonify(signedIn=False, configured=True, clientId=client_id, nonce=nonce)

    @app.post("/api/editor/login")
    def login():
        same_origin()
        client_id = app.config["GOOGLE_CLIENT_ID"]
        if not client_id:
            abort(503)
        data = request.get_json(silent=True)
        credential = data.get("credential") if isinstance(data, dict) else None
        nonce = session.get("nonce")
        if not isinstance(credential, str) or len(credential) > 12000 or not nonce:
            abort(400)
        if int(time.time()) - session.get("nonce_time", 0) >= 600:
            abort(401)
        try:
            claims = id_token.verify_oauth2_token(credential, transport, client_id)
        except (ValueError, GoogleAuthError):
            abort(401)
        token_nonce = claims.get("nonce")
        email = claims.get("email")
        if (not isinstance(token_nonce, str) or not token_nonce.isascii()
                or not compare_digest(token_nonce, nonce)
                or claims.get("email_verified") is not True
                or not isinstance(email, str) or email.lower() != OWNER):
            abort(403)
        session.clear()
        session.permanent = True
        session["login_id"] = token_urlsafe(32)
        session["csrf"] = token_urlsafe(32)
        with closing(db.connect()) as conn, conn:
            now = int(time.time())
            conn.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
            conn.execute("INSERT INTO sessions VALUES (?, ?)", (session["login_id"], now + SESSION_SECONDS))
        return jsonify(signedIn=True)

    @app.post("/api/editor/logout")
    @require_login
    def logout():
        with closing(db.connect()) as conn, conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session["login_id"],))
        session.clear()
        return "", 204

    return require_login
