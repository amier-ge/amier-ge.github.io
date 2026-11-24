from contextlib import closing
from datetime import datetime, timedelta, timezone
from uuid import UUID

from flask import Blueprint, abort, jsonify, request


SEOUL = timezone(timedelta(hours=9))
ORIGINS = {
    "https://amier.ge",
    "https://www.amier.ge",
    "https://amier-ge.github.io",
}


def day_in_seoul():
    return datetime.now(SEOUL).date().isoformat()


def counter(db, now=day_in_seoul):
    routes = Blueprint("visitors", __name__, url_prefix="/api/visitors")

    @routes.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.vary.add("Origin")
        origin = request.headers.get("Origin")
        if origin in ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
        return response

    def snapshot(conn, day):
        today = conn.execute("SELECT count FROM days WHERE day = ?", (day,)).fetchone()
        total = conn.execute("SELECT count FROM totals WHERE key = 1").fetchone()
        return jsonify(today=today["count"] if today else 0, total=total["count"])

    @routes.get("/stats")
    def stats():
        with closing(db.connect()) as conn:
            conn.execute("BEGIN")
            return snapshot(conn, now())

    @routes.post("/visit")
    def visit():
        if request.headers.get("Origin") not in ORIGINS:
            abort(403)
        if request.mimetype != "text/plain" or request.content_length != 36:
            abort(400)
        try:
            supplied = request.get_data(as_text=True)
            tab = UUID(supplied)
            if tab.version != 4 or str(tab) != supplied:
                raise ValueError
        except ValueError:
            abort(400)

        day = now()
        with closing(db.connect()) as conn, conn:
            created = conn.execute(
                "INSERT OR IGNORE INTO visits VALUES (?, ?)", (str(tab), day)
            ).rowcount
            if created:
                conn.execute("UPDATE totals SET count = count + 1 WHERE key = 1")
                conn.execute(
                    "INSERT INTO days VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET count = count + 1",
                    (day,),
                )
            return snapshot(conn, day)

    return routes
