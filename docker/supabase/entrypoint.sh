#!/bin/sh
# Run the Supabase CLI local stack from inside a Compose service.
#
# The Docker socket is mounted so the CLI can start the official local Supabase
# containers on the host daemon. The repository is mounted at the same absolute
# path inside and outside the container, so any host paths the CLI passes to
# Docker remain valid.
set -eu

cleanup() {
    echo "Stopping local Supabase stack..."
    supabase stop --no-backup >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "Starting local Supabase stack..."
supabase start

echo "Local Supabase is ready. Keeping the Compose service alive."
# Short sleeps let the TERM trap run promptly when `docker compose down`
# stops this wrapper, so the CLI stack is stopped too.
while :; do
    sleep 1
done
