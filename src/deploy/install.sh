#!/usr/bin/env bash
set -Eeuo pipefail

read -r client_id
client_id="${client_id%$'\r'}"
if [[ ! "$client_id" =~ ^[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com$ ]]; then
    printf 'Invalid Google web client ID.\n' >&2
    exit 1
fi

source_dir="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
base=/opt/amier-blog
active="$base/current"
default_site=/etc/nginx/sites-available/default
blog_snippet=/etc/nginx/snippets/amier-blog-locations.conf
blog_limits=/etc/nginx/conf.d/amier-blog-rates.conf
service_file=/etc/systemd/system/amier-blog.service
env_file=/etc/amier-blog/editor.env
hugo_version=0.162.1
install -d -m 0755 "$base" "$base/releases" "$base/bin"
release="$(mktemp -d "$base/releases/release.XXXXXXXX")"
chmod 0755 "$release"
stage="$(mktemp -d /run/amier-blog-deploy.XXXXXXXX)"
cleanup() {
    for file in original-nginx new-nginx old-service old-snippet old-limits old-env checksums hugo.deb; do
        rm -f -- "$stage/$file"
    done
    if [[ -d "$stage/hugo-extracted" ]]; then
        rm -r -- "$stage/hugo-extracted"
    fi
    rmdir -- "$stage"
}
trap cleanup EXIT

if ! grep -Eq '^[[:space:]]*root (/var/www/html|/var/lib/amier-blog/public);' "$default_site" ||
   ! grep -Fq 'server_name amier.ge www.amier.ge;' "$default_site"; then
    printf 'Unexpected Nginx site configuration. No cutover performed.\n' >&2
    exit 1
fi
cp -- "$default_site" "$stage/original-nginx"
for pair in "$service_file old-service" "$blog_snippet old-snippet" "$blog_limits old-limits" "$env_file old-env"; do
    read -r original saved <<< "$pair"
    if [[ -f "$original" ]]; then cp -p -- "$original" "$stage/$saved"; fi
done
previous="$(readlink "$active" || true)"
if [[ -e "$active" && ! -L "$active" ]]; then exit 1; fi

if ! id amier-blog >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /var/lib/amier-blog --shell /usr/sbin/nologin amier-blog
fi
if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv
fi
if ! "$base/bin/hugo" version 2>/dev/null | grep -Fq "v$hugo_version"; then
    url="https://github.com/gohugoio/hugo/releases/download/v$hugo_version"
    package="hugo_extended_${hugo_version}_linux-amd64.deb"
    curl -fsSL --retry 2 "$url/$package" -o "$stage/hugo.deb"
    curl -fsSL --retry 2 "$url/hugo_${hugo_version}_checksums.txt" -o "$stage/checksums"
    expected="$(awk -v package="$package" '$2 == package { print $1 }' "$stage/checksums")"
    [[ "$expected" =~ ^[a-fA-F0-9]{64}$ ]]
    printf '%s  %s\n' "$expected" "$stage/hugo.deb" | sha256sum -c
    dpkg-deb -x "$stage/hugo.deb" "$stage/hugo-extracted"
    extracted="$(find "$stage/hugo-extracted" -type f -name hugo -print)"
    [[ -f "$extracted" ]]
    install -m 0755 "$extracted" "$base/bin/hugo"
fi

cp -R -- "$source_dir/src" "$source_dir/assets" "$source_dir/blog" "$source_dir/hugo.toml" "$release"
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --disable-pip-version-check --quiet -r "$release/src/server/requirements.txt"
"$base/bin/hugo" --source "$release" --destination "$release/.build-check" --baseURL https://amier.ge/ --minify --noBuildLock >/dev/null
test -s "$release/.build-check/blog/1/index.html"
test -s "$release/.build-check/en/blog/welcome/index.html"
rm -r -- "$release/.build-check"

install -d -m 0700 /etc/amier-blog
install -d -m 0755 -o amier-blog -g amier-blog /var/lib/amier-blog
if [[ -e "$env_file" ]]; then
    session_key="$(sed -n 's/^AMIER_SESSION_KEY=//p' "$env_file")"
else
    session_key="$(openssl rand -hex 32)"
fi
[[ "$session_key" =~ ^[a-f0-9]{64}$ ]]

restore() {
    local saved="$1" destination="$2"
    if [[ -f "$saved" ]]; then cp -p -- "$saved" "$destination"; else rm -f -- "$destination"; fi
}
rollback() {
    trap - ERR
    set +e
    printf 'Deployment failed during cutover. Restoring previous configuration.\n' >&2
    cp -- "$stage/original-nginx" "$default_site"
    restore "$stage/old-service" "$service_file"
    restore "$stage/old-snippet" "$blog_snippet"
    restore "$stage/old-limits" "$blog_limits"
    restore "$stage/old-env" "$env_file"
    if [[ -n "$previous" ]]; then
        ln -sfn -- "$previous" "$active"
    else
        systemctl disable --now amier-blog.service >/dev/null 2>&1 || true
        rm -f -- "$active"
    fi
    systemctl daemon-reload
    if [[ -n "$previous" ]]; then systemctl restart amier-blog.service; fi
    nginx -t && systemctl reload nginx
    exit 1
}
trap rollback ERR

(umask 077; printf 'AMIER_SESSION_KEY=%s\nAMIER_GOOGLE_CLIENT_ID=%s\n' "$session_key" "$client_id" > "$env_file")
ln -sfn -- "$release" "$active"
install -m 0644 "$release/src/deploy/amier-blog.service" "$service_file"
systemctl daemon-reload
systemctl restart amier-blog.service
for retry in $(seq 1 20); do
    if curl -fs --max-time 2 http://127.0.0.1:18742/api/visitors/stats; then break; fi
    sleep 1
done
curl -fsS --max-time 2 http://127.0.0.1:18742/api/editor/session | grep -q '"configured":true'
test -s /var/lib/amier-blog/public/blog/1/index.html
install -m 0644 "$release/src/deploy/amier-blog-rates.conf" "$blog_limits"
install -m 0644 "$release/src/deploy/amier-blog-locations.conf" "$blog_snippet"
if ! grep -Fq 'include snippets/amier-blog-locations.conf;' "$default_site"; then
    awk '
      /^[[:space:]]*root \/var\/www\/html;/ {
        print "\troot /var/lib/amier-blog/public;"
        print "\tinclude snippets/amier-blog-locations.conf;"
        next
      }
      { print }
    ' "$default_site" > "$stage/new-nginx"
    install -m 0644 "$stage/new-nginx" "$default_site"
fi
nginx -t
systemctl reload nginx
for retry in $(seq 1 10); do
    if curl -fs --max-time 2 --resolve amier.ge:443:127.0.0.1 https://amier.ge/editor/ >/dev/null; then break; fi
    sleep 1
done
curl -fsS --max-time 5 --resolve amier.ge:443:127.0.0.1 https://amier.ge/editor/ >/dev/null
curl -fsS --max-time 5 --resolve amier.ge:443:127.0.0.1 https://amier.ge/blog/1/ >/dev/null
systemctl enable amier-blog.service
trap - ERR
printf '\nBlog deployment active.\n'
