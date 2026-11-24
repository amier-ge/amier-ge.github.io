"""Build GitHub Pages redirects from Hugo routes and alias canonical URLs."""

import argparse
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import quote, urlsplit


ORIGIN = "https://amier.ge"
LEGACY_HOSTS = {"amier-ge.github.io", "amier.ge"}


class CanonicalLink(HTMLParser):
    def __init__(self):
        super().__init__()
        self.url = None

    def handle_starttag(self, tag, attrs):
        if tag == "link" and self.url is None:
            attributes = dict(attrs)
            if "canonical" in (attributes.get("rel") or "").lower().split():
                self.url = attributes.get("href")


def destination_for(source, relative):
    parser = CanonicalLink()
    # Canonical links from Hugo aliases are in the head, including minified output.
    with source.open(encoding="utf-8") as html:
        parser.feed(html.read(32 * 1024))
    if parser.url:
        try:
            canonical = urlsplit(parser.url)
        except ValueError:
            canonical = None
        if canonical and canonical.scheme == "https" and canonical.netloc in LEGACY_HOSTS:
            return ORIGIN + quote(canonical.path or "/", safe="/%")
    if relative.name == "index.html":
        path = "/" + "/".join(relative.parts[:-1])
        if path != "/":
            path += "/"
    else:
        path = "/" + relative.as_posix()
    return ORIGIN + quote(path, safe="/%")


def render_redirect(destination, *, missing=False):
    html_url = escape(destination, quote=True)
    js_url = json.dumps(destination)
    pass_path = "  target.pathname = window.location.pathname;\n" if missing else ""
    metadata = (
        '<meta name="robots" content="noindex">' if missing
        else f'<link rel="canonical" href="{html_url}">'
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>amier.ge로 이동</title>
{metadata}
<script>
  const target = new URL({js_url});
{pass_path}  target.search = window.location.search;
  target.hash = window.location.hash;
  window.location.replace(target.href);
</script>
<noscript><meta http-equiv="refresh" content="0; url={html_url}"></noscript>
</head>
<body><p><a href="{html_url}">amier.ge로 이동</a></p></body>
</html>
"""


def build_redirects(source, output):
    source, output = source.resolve(), output.resolve()
    if not (source / "index.html").is_file():
        raise ValueError("The source must contain a built Hugo site.")
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("Keep the output separate from the input site.")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("The output must be empty to prevent old content being deployed.")
    count = 0
    for page in sorted(source.rglob("*.html")):
        relative = page.relative_to(source)
        if relative.name == "404.html":
            continue
        redirect = output / relative
        redirect.parent.mkdir(parents=True, exist_ok=True)
        redirect.write_text(render_redirect(destination_for(page, relative)), encoding="utf-8")
        count += 1
    (output / "404.html").write_text(render_redirect(ORIGIN + "/", missing=True), encoding="utf-8")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    count = build_redirects(args.source, args.output)
    print(f"Generated {count} redirects and a path-preserving 404 page.")


if __name__ == "__main__":
    main()
