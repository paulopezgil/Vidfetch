#!/usr/bin/env bash
# Create a known local administrator in the Compose Supabase stack.
#
# This service is local-development only. It never runs in production and the
# credentials below are intentionally public and disposable.
set -euo pipefail

: "${SUPABASE_URL:?SUPABASE_URL is required}"
: "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is required}"
: "${DATABASE_URL:?DATABASE_URL is required}"
: "${DB_SCHEMA:=public}"
: "${LOCAL_ADMIN_EMAIL:=admin@local.test}"
: "${LOCAL_ADMIN_PASSWORD:=password123}"

case "$DB_SCHEMA" in
    *[!a-z0-9_]*|'')
        echo "Invalid DB_SCHEMA: $DB_SCHEMA" >&2
        exit 1
        ;;
esac

AUTH_URL="${SUPABASE_URL%/}/auth/v1"
email_sql="${LOCAL_ADMIN_EMAIL//\'/\'\'}"

echo "Waiting for local Supabase Auth..."
until curl -fsS "$AUTH_URL/health" >/dev/null 2>&1; do
    sleep 2
done

echo "Creating local administrator ${LOCAL_ADMIN_EMAIL}..."
payload="$(jq -nc \
    --arg email "$LOCAL_ADMIN_EMAIL" \
    --arg password "$LOCAL_ADMIN_PASSWORD" \
    '{email: $email, password: $password, email_confirm: true}')"

status="$(curl -sS -o /tmp/local-user.json -w '%{http_code}' \
    -X POST "$AUTH_URL/admin/users" \
    -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
    -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
    -H "Content-Type: application/json" \
    --data "$payload" || echo 000)"

case "$status" in
    200|201)
        echo "Local administrator created."
        ;;
    422)
        echo "Local administrator already exists; updating the profile."
        ;;
    *)
        echo "Could not create the local administrator (HTTP ${status}):" >&2
        cat /tmp/local-user.json >&2 || true
        exit 1
        ;;
esac

# The auth trigger creates the profile asynchronously in the same transaction.
for _ in $(seq 1 30); do
    if psql "$DATABASE_URL" -tAc \
        "select 1 from \"${DB_SCHEMA}\".profiles where lower(email) = lower('${email_sql}')" \
        | grep -q 1; then
        break
    fi
    sleep 1
done

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
    -c "update \"${DB_SCHEMA}\".profiles
           set is_approved = true,
               app_role = 'admin',
               approved_at = now(),
               approved_by = id
         where lower(email) = lower('${email_sql}');"

echo
echo "Local administrator ready:"
echo "  email:    ${LOCAL_ADMIN_EMAIL}"
echo "  password: ${LOCAL_ADMIN_PASSWORD}"
echo "Open http://localhost:5173 and use the local development sign-in."
