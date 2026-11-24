import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import tomllib

from markdown_it import MarkdownIt

from media import UPLOAD_NAME, UPLOAD_PREFIX


VIDEO_NAME = r"[a-f0-9]{32}\.(?:mp4|webm)"
VIDEO_MARKUP = re.compile(
    r'<video controls preload="metadata" src="' + re.escape(UPLOAD_PREFIX) + f"({VIDEO_NAME})" + r'"></video>'
)
MEDIA_ATTRIBUTE = re.compile(r'(\b(?:src|href)=")' + re.escape(UPLOAD_PREFIX) + f'({UPLOAD_NAME})"')
VIDEO_LINK = re.compile(r'<a href="(/api/editor/media/' + VIDEO_NAME + r')">업로드 영상</a>')
HOME_TEMPLATE = '{{ .RenderString (dict "display" "block" "markup" "markdown") .Site.Data.preview.body }}'


class PreviewError(Exception):
    pass


class MarkdownPreview:
    def __init__(self, site_config, scratch, hugo):
        with site_config.open("rb") as handle:
            settings = tomllib.load(handle)
        markup = settings["markup"]
        # The editor consumes HTML in a privileged page. Keep authored raw HTML
        # disabled here, while retaining the published site's Markdown extensions.
        markup["goldmark"]["renderer"]["unsafe"] = False
        self.config = {
            "markup": markup,
            "baseURL": "https://amier.ge/",
            "enableEmoji": settings.get("enableEmoji", False),
            "defaultContentLanguage": settings.get("defaultContentLanguage", "ko"),
            "disableKinds": ["404", "page", "section", "taxonomy", "term", "RSS", "sitemap"],
            "outputs": {"home": ["HTML"]},
            "security": {"http": {"urls": ["^$"], "methods": ["^$"]}},
        }
        self.scratch = scratch
        self.hugo = hugo
        self.tokenizer = MarkdownIt("commonmark", {"html": True})

    def prepare_videos(self, body):
        if "<video" not in body:
            return body
        lines = body.splitlines(keepends=True)
        # The editor emits one standalone HTML block for each upload. Only
        # replace those blocks, leaving the same text inside fenced code intact.
        tokens = self.tokenizer.parse(body)
        for token in reversed(tokens):
            if token.type not in {"html_block", "inline"} or token.map is None:
                continue
            video = VIDEO_MARKUP.fullmatch(token.content.strip())
            if video:
                start, end = token.map
                name = video.group(1)
                lines[start:end] = [f"[업로드 영상]({UPLOAD_PREFIX}{name})\n"]
        return "".join(lines)

    def render(self, body):
        if not body.strip():
            return ""
        try:
            with TemporaryDirectory(prefix="markdown-", dir=self.scratch) as work:
                root = Path(work)
                (root / "layouts").mkdir()
                (root / "data").mkdir()
                (root / "hugo.json").write_text(json.dumps(self.config), encoding="utf-8")
                (root / "layouts/index.html").write_text(HOME_TEMPLATE, encoding="utf-8")
                payload = {"body": self.prepare_videos(body)}
                (root / "data/preview.json").write_text(json.dumps(payload), encoding="utf-8")
                subprocess.run(
                    [self.hugo, "--source", str(root), "--cacheDir", str(root / "cache"),
                     "--noBuildLock", "--environment", "production"],
                    check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
                )
                html = (root / "public/index.html").read_text(encoding="utf-8")
        except (OSError, subprocess.SubprocessError) as error:
            raise PreviewError("Hugo preview failed") from error
        html = MEDIA_ATTRIBUTE.sub(r'\1/api/editor/media/\2"', html)
        return VIDEO_LINK.sub(r'<video controls preload="metadata" src="\1"></video>', html)
