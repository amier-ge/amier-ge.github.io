from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
from uuid import uuid4

from app import create_app


ORIGIN = "https://amier.ge"


class BlogTest(TestCase):
    def setUp(self):
        self.work = TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.app = create_app({
            "TESTING": True,
            "STATE_DIR": self.work.name,
            "SECRET_KEY": "test-secret-for-isolated-local-verification",
            "GOOGLE_CLIENT_ID": "client.apps.googleusercontent.com",
        })
        self.client = self.app.test_client()
        self.content = self.app.extensions["content"]

    def request(self, method, route, **kwargs):
        return self.client.open(route, method=method, base_url=ORIGIN, **kwargs)

    def login(self, email="amierge.df@gmail.com", verified=True, nonce=None):
        config = self.request("GET", "/api/editor/session").json
        claims = {
            "nonce": nonce or config["nonce"], "email_verified": verified, "email": email,
            "sub": "test-identification",
        }
        with patch("auth.id_token.verify_oauth2_token", return_value=claims) as verify:
            result = self.request("POST", "/api/editor/login", json={"credential": "mocked"},
                                  headers={"Origin": ORIGIN})
        self.assertEqual(verify.call_args.args[2], "client.apps.googleusercontent.com")
        return result

    def authorized(self):
        self.assertEqual(self.login().status_code, 200)
        session = self.request("GET", "/api/editor/session").json
        return {"Origin": ORIGIN, "X-CSRF-Token": session["csrf"]}

    def test_counter_seed_duplicated_tab_and_midnight(self):
        route = "/api/visitors/stats"
        self.assertEqual(self.request("GET", route).json, {"today": 0, "total": 968})
        first, second, third = [str(uuid4()) for _ in range(3)]

        def visit(tab, origin=ORIGIN):
            return self.request("POST", "/api/visitors/visit", data=tab,
                                content_type="text/plain", headers={"Origin": origin})

        self.assertEqual(visit(first, "https://example.org").status_code, 403)
        self.assertEqual(visit(first).json, {"today": 1, "total": 969})
        self.assertEqual(visit(first).json, {"today": 1, "total": 969})
        self.assertEqual(visit(second).json, {"today": 2, "total": 970})
        with patch("visitors.datetime") as clock:
            clock.now.return_value.date.return_value.isoformat.return_value = "9998-01-01"
            self.assertEqual(visit(first).json, {"today": 0, "total": 970})
            self.assertEqual(visit(third).json, {"today": 1, "total": 971})

    def test_owner_login_nonce_and_csrf(self):
        self.assertEqual(self.request("GET", "/api/editor/posts").status_code, 401)
        self.assertEqual(self.login(email="someone@gmail.com").status_code, 403)
        self.assertEqual(self.login(verified=False).status_code, 403)
        self.assertEqual(self.login(nonce="incorrect").status_code, 403)
        headers = self.authorized()
        self.assertEqual(len(self.request("GET", "/api/editor/posts").json["posts"]), 13)
        self.assertEqual(self.request("POST", "/api/editor/preview", json={"body": "draft"},
                                      headers={"Origin": ORIGIN}).status_code, 403)
        self.assertEqual(self.request("POST", "/api/editor/logout", headers=headers).status_code, 204)
        self.assertEqual(self.request("GET", "/api/editor/posts").status_code, 401)

    def test_markdown_media_draft_about_and_publish(self):
        headers = self.authorized()
        route = "/api/editor/document/"
        media = self.request(
            "POST", "/api/editor/upload", data={"file": (BytesIO(b"GIF89a" + b"0" * 12), "check.gif")},
            headers=headers,
        )
        self.assertEqual(media.status_code, 201)
        url, name = media.json["url"], media.json["name"]
        body = "## Example\n\n![image](" + url + ")\n\n<script>alert(1)</script>"
        preview = self.request("POST", "/api/editor/preview", json={"body": body}, headers=headers)
        self.assertIn("/api/editor/media/" + name, preview.json["html"])
        self.assertNotIn("<script>", preview.json["html"])
        post = {
            "kind": "post", "lang": "ko", "number": 0, "revision": 0, "title": "Example",
            "date": "2020-01-01", "categories": ["Others"], "tags": ["test"], "body": body,
        }
        draft = self.request("POST", route + "save", json=post, headers=headers).json
        self.assertEqual(draft["number"], 14)
        self.assertFalse(draft["published"])
        self.assertEqual(self.request("POST", route + "save", json={**draft, "revision": 0},
                                      headers=headers).status_code, 409)
        builds = []

        @contextmanager
        def record(destination):
            builds.append(destination)
            yield

        with patch.object(self.content.publisher, "activate", record):
            result = self.request("POST", route + "publish", json={**draft, "body": body.split("<script>")[0]},
                                  headers=headers)
            self.assertEqual(result.status_code, 200, result.json)
            self.assertTrue(result.json["published"])
            self.assertFalse(result.json["hasDraft"])
            self.assertTrue((builds[-1] / "blog/14/index.html").is_file())
            self.assertTrue((builds[-1] / url.lstrip("/")).is_file())
            about = self.content.load("about", 0, "en")
            about["body"] = "## About edit smoke test"
            self.assertEqual(self.request("POST", route + "publish", json=about, headers=headers).status_code, 200)
            self.assertIn("About edit smoke test", (builds[-1] / "en/about/index.html").read_text(encoding="utf-8"))

    def test_numbered_routes_and_legacy_aliases(self):
        target = self.content.publisher.build(self.content, {})
        for i in range(1, 14):
            self.assertTrue((target / "blog" / str(i) / "index.html").is_file())
        self.assertIn("data-g-term=blog/welcome/", (target / "blog/1/index.html").read_text(encoding="utf-8"))
        for old, new in (("blog/welcome", "blog/1"), ("en/blog/welcome", "en/blog/1")):
            self.assertIn(ORIGIN + "/" + new + "/", (target / old / "index.html").read_text(encoding="utf-8"))
        for preserved in ("about/index.html", "contact/index.html", "img/posts/check.png", "index.xml"):
            self.assertTrue((target / preserved).is_file())


if __name__ == "__main__":
    main()
