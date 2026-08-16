#!/usr/bin/env bash
set -euo pipefail

site=/etc/nginx/sites-enabled/twitchbot
candidate=/tmp/shedlink-twitchbot.production.conf
upload=/tmp/RimLink-0.1.1.zip
release_dir=/srv/shedlink/releases
release_name=RimLink-0.1.1.zip
expected_size=63673
expected_sha=4e9656cb84b574691482938967928b0c50ad3cafd3cb7e41e79a12cb7ed42381
backup="/root/twitchbot.nginx.bak.$(date -u +%Y%m%dT%H%M%SZ)"

test -f "$candidate"
test -f "$upload"
test "$(stat -c %s "$upload")" = "$expected_size"
test "$(sha256sum "$upload" | awk '{print $1}')" = "$expected_sha"

install -d -o root -g root -m 0755 "$release_dir"
if test -e "$release_dir/$release_name"; then
    test "$(stat -c %s "$release_dir/$release_name")" = "$expected_size"
    test "$(sha256sum "$release_dir/$release_name" | awk '{print $1}')" = "$expected_sha"
else
    install -o root -g root -m 0644 "$upload" "$release_dir/.$release_name.pending"
    mv "$release_dir/.$release_name.pending" "$release_dir/$release_name"
fi

cp -a "$site" "$backup"
install -o root -g root -m 0644 "$candidate" "$site"
if ! nginx -t; then
    cp -a "$backup" "$site"
    nginx -t
    exit 1
fi
systemctl reload nginx

test "$(curl -sS -o /dev/null -w '%{http_code}' --resolve shedoy23.ru:443:127.0.0.1 \
    "https://shedoy23.ru/releases/$release_name")" = 200
test "$(curl -sS -o /dev/null -w '%{http_code}' \
    "http://127.0.0.1/releases/$release_name" -H 'Host: shedoy23.ru')" = 404
test "$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)" = 200

echo "PUBLISHED https://shedoy23.ru/releases/$release_name"
echo "NGINX_BACKUP=$backup"
