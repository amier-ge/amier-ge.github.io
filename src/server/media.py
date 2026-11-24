from pathlib import Path
import re
from uuid import uuid4


UPLOAD_PREFIX = "/img/uploads/"
UPLOAD_NAME = r"[a-f0-9]{32}\.(?:png|jpg|gif|webp|mp4|webm)"
UPLOAD_RE = re.compile(UPLOAD_NAME, re.ASCII)
MEDIA_REFERENCE = re.compile(re.escape(UPLOAD_PREFIX) + "(" + UPLOAD_NAME + r")(?![\w.])")
MAX_MEDIA = 24 * 1024 * 1024
TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "mp4": "video/mp4", "webm": "video/webm",
}


def extension_for(header):
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    if header[4:8] == b"ftyp":
        return "mp4"
    if header.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in header:
        return "webm"
    raise ValueError("PNG, JPG, GIF, WebP, MP4, WebM 파일만 올릴 수 있습니다.")


class Media:
    def __init__(self, path):
        self.path = path
        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)

    def upload(self, stream):
        content = stream.read(MAX_MEDIA + 1)
        if len(content) > MAX_MEDIA:
            raise ValueError("파일 한 개의 최대 크기는 24 MB입니다.")
        suff = extension_for(content[:256])
        name = uuid4().hex + "." + suff
        with (self.path / name).open("xb") as stored:
            stored.write(content)
        return {"url": UPLOAD_PREFIX + name, "name": name, "type": TYPES[suff]}

    def file(self, name):
        if not UPLOAD_RE.fullmatch(name):
            raise LookupError
        path = self.path / name
        if not path.is_file():
            raise LookupError
        return path, TYPES[Path(name).suffix[1:]]
