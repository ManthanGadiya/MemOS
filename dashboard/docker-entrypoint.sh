#!/bin/sh
# Render the nginx config from MEMOS_API_TARGET (default: http://backend:8000)
# then start nginx. Used as the dashboard container entrypoint so the backend
# upstream host can vary between docker compose and standalone runs.

set -eu

API_TARGET="${MEMOS_API_TARGET:-http://backend:8000}"

sed "s|__MEMOS_API_UPSTREAM__|${API_TARGET}|g" \
    /etc/nginx/conf.d/default.conf.template \
    > /etc/nginx/conf.d/default.conf

exec nginx -g "daemon off;"
