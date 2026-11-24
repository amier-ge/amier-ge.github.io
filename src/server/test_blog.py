from contextlib import contextmanager
from html import unescape
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

    def test_markdown_preview_uses_published_hugo_syntax(self):
        headers = self.authorized()
        video_name = "a" * 32 + ".mp4"
        video = f'<video controls preload="metadata" src="/img/uploads/{video_name}"></video>'
        fence = chr(96) * 3
        body = "\n".join([
            "# 제목 1", "## 제목 2", "### 제목 3", "#### 제목 4", "##### 제목 5", "###### 제목 6",
            "", "##공백없음", "", "Setext heading", "--------------", "",
            "**굵게** *기울임* ~~취소~~ " + chr(96) + "인라인 코드" + chr(96) + " :smile:",
            "", "> 인용문", "", "- 목록", "  - 중첩 목록", "", "3. 번호 목록",
            "", "- [x] 완료", "- [ ] 할 일", "", "---", "",
            "| 항목 | 값 |", "| --- | ---: |", "| 표 | 10 |", "",
            "[링크][ref]", "", "[ref]: https://example.org", "",
            "<https://example.net>", "", "![이미지](/img/posts/check.png)", "",
            "각주가 있는 문장[^note].", "", "[^note]: 각주 내용.", "",
            "용어", ": 정의", "", fence + "python", "print('미리보기')", fence, "",
            video, "", fence + "html", video, fence, "",
            "<script>alert(1)</script>", "", "[unsafe](javascript:alert(1))",
        ])
        preview = self.request("POST", "/api/editor/preview", json={"body": body}, headers=headers)
        self.assertEqual(preview.status_code, 200, preview.json)
        html = preview.json["html"]
        for level in range(1, 7):
            self.assertRegex(html, rf"<h{level}\b[^>]*>제목 {level}</h{level}>")
        for expected in ("<strong>굵게</strong>", "<em>기울임</em>", "<del>취소</del>",
                         "<code>인라인 코드</code>", "<blockquote>", "<ul>", '<ol start="3">',
                         'type="checkbox"', "<hr", "<table>", 'href="https://example.org"',
                         'href="https://example.net"', 'src="/img/posts/check.png"',
                         'class="footnotes"', "<dl>", 'class="language-python"', "##공백없음"):
            self.assertIn(expected, html)
        self.assertIn("😄", unescape(html))
        self.assertEqual(html.count("<video "), 1)
        self.assertIn(f'src="/api/editor/media/{video_name}"', html)
        self.assertIn(f"/img/uploads/{video_name}", html)  # Literal inside the HTML code fence.
        self.assertNotIn("<script>", html)
        self.assertNotIn('href="javascript:', html)

        key = ("post", 14, "ko")
        draft = {
            "title": "Markdown coverage", "body": body.replace(video, ""),
            "date": "2020-01-01", "tags": [], "categories": ["Others"], "summary": "",
        }
        build = self.content.publisher.build(self.content, {key: draft}, required=key)
        public = (build / "blog/14/index.html").read_text(encoding="utf-8")
        self.assertRegex(public, r"<h2\b[^>]*>제목 2</h2>")
        self.assertIn("<table>", public)
        self.assertIn("각주 내용", public)

    def test_hidden_post_removes_both_languages_aliases_and_feeds(self):
        headers = self.authorized()
        route = "/api/editor/document/"
        old_english = self.content.load("post", 1, "en")
        korean = self.content.load("post", 1, "ko")
        draft = self.request("POST", route + "save", json={**korean, "hidden": True}, headers=headers)
        self.assertTrue(draft.json["hidden"])
        self.assertTrue(draft.json["public"])
        self.assertFalse(draft.json["currentlyHidden"])

        builds = []

        @contextmanager
        def record(destination):
            builds.append(destination)
            yield

        with patch.object(self.content.publisher, "activate", record):
            result = self.request("POST", route + "publish", json=draft.json, headers=headers)
            self.assertEqual(result.status_code, 200, result.json)
            self.assertTrue(result.json["currentlyHidden"])
            self.assertFalse(self.content.load("post", 1, "en")["public"])
            self.assertTrue(next(p for p in self.content.catalog() if p["number"] == 1)["hidden"])
            self.assertEqual(self.request("POST", route + "publish", json=old_english,
                                          headers=headers).status_code, 409)
            for path in ("blog/1", "en/blog/1", "blog/welcome", "en/blog/welcome"):
                self.assertFalse((builds[-1] / path / "index.html").exists())
            for path in ("blog/index.html", "blog/index.xml", "ko/sitemap.xml",
                         "en/blog/index.html", "en/blog/index.xml", "en/sitemap.xml"):
                self.assertNotIn("/blog/1/", (builds[-1] / path).read_text(encoding="utf-8"))

            english = self.content.load("post", 1, "en")
            result = self.request("POST", route + "publish", json={**english, "hidden": False}, headers=headers)
            self.assertEqual(result.status_code, 200, result.json)
            self.assertTrue(self.content.load("post", 1, "ko")["public"])
            self.assertTrue((builds[-1] / "blog/1/index.html").is_file())
            self.assertTrue((builds[-1] / "en/blog/1/index.html").is_file())


if __name__ == "__main__":
    main()
