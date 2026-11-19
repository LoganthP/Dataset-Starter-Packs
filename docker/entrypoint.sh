#!/bin/sh
# Pack downloads (packs/<slug>/data) live on the /data volume too, so they survive container recreation.
set -e
for pack in /app/packs/*/; do
  slug=$(basename "$pack")
  mkdir -p "/data/pack-data/$slug"
done
exec "$@"
