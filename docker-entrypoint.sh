#!/bin/sh
set -e

# Fail fast if required runtimes are missing.
node --version
ffmpeg -version 2>/dev/null | head -1

# Bind-mounted directories may be owned by root on the host. Make them
# writable by the application user before dropping privileges.
mkdir -p /app/downloads /app/data
chown -R appuser:appuser /app/downloads /app/data

# Run the application as the non-root user.
exec gosu appuser "$@"
