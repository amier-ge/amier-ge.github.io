from contextlib import closing
from datetime import date
import json
from pathlib import Path
import threading
import tomllib

import yaml

from visitors import day_in_seoul


LANGUAGES = {"ko", "en"}
EDITABLE = {"title", "summary", "date", "categories", "tags"}


def read_markdown(path):
    content = path.read_text(encoding="utf-8-sig")
    opening, front, body = content.split("---\n", 2)
    if opening.strip():
        raise ValueError(f"Invalid front matter in {path.name}")
    metadata = yaml.safe_load(front)
    if not isinstance(metadata, dict):
        raise ValueError(f"Invalid front matter in {path.name}")
    return metadata, body.removeprefix("\n")


def normalize_day(value):
    if not isinstance(value, str):
        raise ValueError("날짜를 YYYY-MM-DD 형식으로 입력하세요.")
    try:
        normalized = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("날짜를 YYYY-MM-DD 형식으로 입력하세요.") from error
    if normalized.isoformat() != value:
        raise ValueError("날짜를 YYYY-MM-DD 형식으로 입력하세요.")
    return value


class Content:
    def __init__(self, repo, db, publisher):
        self.repo = repo
        self.db = db
        self.publisher = publisher
        self.lock = threading.Lock()
        self.seeds = {}
        self.post_names = {}
        with (repo / "hugo.toml").open("rb") as config:
            self.categories = tomllib.load(config)["params"]["categories"]
        for path in sorted((repo / "blog").glob("*.md")):
            if not path.name.startswith("_"):
                meta, body = read_markdown(path)
                number = int(meta["slug"])
                lang = "en" if path.name.endswith(".en.md") else "ko"
                self.seeds[("post", number, lang)] = (meta, body)
                self.post_names[number] = path.name.removesuffix(".md").removesuffix(".en")
        for lang in LANGUAGES:
            path = repo / self.relative_path("about", 0, lang)
            self.seeds[("about", 0, lang)] = read_markdown(path)

    def relative_path(self, kind, number, lang):
        extension = ".en.md" if lang == "en" else ".md"
        if kind == "about":
            return Path("src/site/content/about") / ("_index" + extension)
        base = self.post_names.get(number, str(number))
        return Path("blog") / (base + extension)

    def seed_document(self, key):
        meta, body = self.seeds.get(key, ({}, ""))
        # A translation starts with the Korean date, so both versions sort together.
        parent = self.seeds.get((key[0], key[1], "ko"), ({}, ""))[0]
        return {
            "title": meta.get("title", ""),
            "summary": meta.get("summary", ""),
            "date": str(meta.get("date", parent.get("date", day_in_seoul())))[:10],
            "categories": meta.get("categories", parent.get("categories", [])),
            "tags": meta.get("tags", []),
            "body": body,
        }

    def lookup(self, conn, key):
        return conn.execute(
            "SELECT * FROM documents WHERE kind = ? AND number = ? AND lang = ?", key
        ).fetchone()

    def catalog(self):
        articles = {}
        with closing(self.db.connect()) as conn:
            rows = conn.execute("SELECT * FROM documents WHERE kind = 'post'").fetchall()
        revisions = {(row["kind"], row["number"], row["lang"]): row for row in rows}
        for key in self.seeds.keys() | revisions.keys():
            kind, number, lang = key
            if kind != "post":
                continue
            row = revisions.get(key)
            stored = (row["draft"] or row["published"]) if row else None
            document = json.loads(stored) if stored else self.seed_document(key)
            post = articles.setdefault(number, {"number": number, "languages": {}})
            post["languages"][lang] = {
                "title": document["title"],
                "draft": bool(row and row["draft"]),
                "published": bool((row and row["published"]) or key in self.seeds),
            }
        return sorted(articles.values(), key=lambda post: post["number"], reverse=True)

    def exists(self, conn, number):
        return number in self.post_names or conn.execute(
            "SELECT 1 FROM documents WHERE kind = 'post' AND number = ? LIMIT 1", (number,)
        ).fetchone() is not None

    def load(self, kind, number, lang):
        key = (kind, number, lang)
        with closing(self.db.connect()) as conn:
            if kind == "post" and number and not self.exists(conn, number):
                raise LookupError
            row = self.lookup(conn, key)
            document = self.seed_document(key)
            if key not in self.seeds and kind == "post" and lang == "en":
                korean = self.lookup(conn, ("post", number, "ko"))
                if korean and (korean["published"] or korean["draft"]):
                    document["date"] = json.loads(korean["published"] or korean["draft"])["date"]
            if row and (row["draft"] or row["published"]):
                document = json.loads(row["draft"] or row["published"])
            return {
                **document, "kind": kind, "number": number, "lang": lang,
                "revision": row["revision"] if row else 0,
                "published": bool(key in self.seeds or (row and row["published"])),
                "hasDraft": bool(row and row["draft"]),
            }

    def validate(self, kind, fields, publish):
        result = {}
        limits = {"title": 300, "body": 1_000_000}
        if kind == "post":
            limits["summary"] = 4000
        for name, limit in limits.items():
            value = fields.get(name, "")
            if not isinstance(value, str) or len(value) > limit or "\x00" in value:
                raise ValueError(f"{name} 입력을 확인하세요.")
            result[name] = value if name == "body" else value.strip()
        if (publish or kind == "post") and not result["title"]:
            raise ValueError("제목을 입력하세요.")
        if publish and kind == "post" and not result["body"].strip():
            raise ValueError("본문을 입력하세요.")
        if kind == "post":
            result["date"] = normalize_day(fields.get("date"))
            if publish and result["date"] > day_in_seoul():
                raise ValueError("게시일을 오늘 또는 이전 날짜로 지정하세요.")
            for name in ("categories", "tags"):
                values = fields.get(name, [])
                if not isinstance(values, list) or len(values) > 40 or any(
                    not isinstance(item, str) or not item.strip() or len(item) > 80
                    or "\x00" in item for item in values
                ):
                    raise ValueError(f"{name} 입력을 확인하세요.")
                result[name] = list(dict.fromkeys(item.strip() for item in values))
            if any(category not in self.categories for category in result["categories"]):
                raise ValueError("등록된 카테고리를 선택하세요.")
        return result

    def update(self, kind, number, lang, fields, publish):
        document = self.validate(kind, fields, publish)
        encoded = json.dumps(document, ensure_ascii=False)
        desired_revision = fields.get("revision")
        if type(desired_revision) is not int or desired_revision < 0:
            raise ValueError("편집 버전을 확인하세요.")
        with self.lock, closing(self.db.connect()) as conn:
            if kind == "post" and not number:
                last = conn.execute(
                    "SELECT COALESCE(MAX(number), 0) FROM documents WHERE kind = 'post'"
                ).fetchone()[0]
                number = max(last, *self.post_names, 0) + 1
            elif kind == "post" and not self.exists(conn, number):
                raise LookupError
            key = (kind, number, lang)
            previous = self.lookup(conn, key)
            if desired_revision != (previous["revision"] if previous else 0):
                raise RuntimeError("다른 탭에서 수정했습니다. 새로 불러온 뒤 다시 저장하세요.")
            revision = desired_revision + 1
            if publish:
                overlays = self.published(conn)
                overlays[key] = document
                build = self.publisher.build(self, overlays, required=key)
                with self.publisher.activate(build), conn:
                    self.persist(conn, key, None, encoded, revision)
            else:
                with conn:
                    self.persist(conn, key, encoded, previous["published"] if previous else None, revision)
        return self.load(kind, number, lang)

    def publish_initial(self):
        with closing(self.db.connect()) as conn:
            build = self.publisher.build(self, self.published(conn))
        with self.publisher.activate(build):
            pass

    @staticmethod
    def persist(conn, key, draft, published, revision):
        conn.execute(
            """INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(kind, number, lang) DO UPDATE SET
               draft=excluded.draft, published=excluded.published, revision=excluded.revision""",
            (*key, draft, published, revision),
        )

    @staticmethod
    def published(conn):
        return {
            (row["kind"], row["number"], row["lang"]): json.loads(row["published"])
            for row in conn.execute("SELECT * FROM documents WHERE published IS NOT NULL")
        }

    def write_document(self, root, key, document):
        kind, number, lang = key
        original = self.seeds.get(key, ({}, ""))[0]
        meta = {name: value for name, value in original.items() if name not in EDITABLE}
        meta["title"] = document["title"]
        if kind == "post":
            meta.update({name: document[name] for name in EDITABLE if name != "title"})
            meta.update(slug=str(number), draft=False)
            if not original:
                original_korean = self.seeds.get((kind, number, "ko"), ({}, ""))[0]
                if term := original_korean.get("commentTerm"):
                    meta["commentTerm"] = term
        path = root / self.relative_path(kind, number, lang)
        header = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
        path.write_text("---\n" + header + "---\n\n" + document["body"], encoding="utf-8")
