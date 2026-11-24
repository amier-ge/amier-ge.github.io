from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4

from media import MEDIA_REFERENCE


class BuildError(Exception):
    pass


class Publisher:
    def __init__(self, repo, state, media, origin, hugo):
        self.repo = repo
        self.state = state
        self.media = media
        self.origin = origin
        self.hugo = hugo
        self.releases = state / "builds"
        self.releases.mkdir(exist_ok=True)
        self.current = state / "public"

    def build(self, content, overlays, required=None, *, hidden=()):
        destination = self.releases / uuid4().hex
        try:
            with TemporaryDirectory(prefix="hugo-", dir=self.state) as tmp:
                source = Path(tmp)
                shutil.copy2(self.repo / "hugo.toml", source)
                for subtree in ("blog", "assets", "src/site"):
                    shutil.copytree(self.repo / subtree, source / subtree)
                for number in hidden:
                    for lang in ("ko", "en"):
                        (source / content.relative_path("post", number, lang)).unlink(missing_ok=True)
                files = set()
                for key, document in overlays.items():
                    if key[0] == "post" and key[1] in hidden:
                        continue
                    content.write_document(source, key, document)
                    files.update(MEDIA_REFERENCE.findall(document["body"]))
                for name in files:
                    path, _ = self.media.file(name)
                    shutil.copy2(path, source / "assets/uploads" / name)
                subprocess.run(
                    [self.hugo, "--source", str(source), "--destination", str(destination),
                     "--baseURL", self.origin + "/", "--environment", "production",
                     "--gc", "--minify", "--noBuildLock"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    check=True, timeout=40,
                )
                if required:
                    kind, number, lang = required
                    folder = destination / "en" if lang == "en" else destination
                    folder = folder / "blog" / str(number) if kind == "post" else folder / "about"
                    should_exist = kind != "post" or number not in hidden
                    if (folder / "index.html").is_file() != should_exist:
                        raise BuildError("글의 공개 상태를 확인할 수 없습니다.")
        except (LookupError, OSError, subprocess.SubprocessError, BuildError) as error:
            shutil.rmtree(destination, ignore_errors=True)
            if isinstance(error, subprocess.CalledProcessError):
                raise BuildError(error.stderr[-3500:] or error.stdout[-3500:]) from error
            raise BuildError(str(error)) from error
        return destination

    def switch(self, target):
        pointer = self.state / (".public-" + uuid4().hex)
        try:
            pointer.symlink_to(target, target_is_directory=True)
            os.replace(pointer, self.current)
        finally:
            pointer.unlink(missing_ok=True)

    @contextmanager
    def activate(self, destination):
        previous = self.current.resolve() if self.current.is_symlink() else None
        try:
            self.switch(destination)
        except OSError:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        try:
            yield
        except Exception:
            if previous:
                self.switch(previous)
            else:
                self.current.unlink()
            shutil.rmtree(destination, ignore_errors=True)
            raise
        retained = {destination, previous}
        for release in self.releases.iterdir():
            if release not in retained and release.is_dir() and not release.is_symlink():
                shutil.rmtree(release, ignore_errors=True)
