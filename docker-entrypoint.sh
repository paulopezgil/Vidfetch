#!/bin/sh
set -e

# Fail fast if required runtimes are missing.
node --version
ffmpeg -version 2>/dev/null | head -1

# Bind-mounted media may be owned by root on the host. Make it writable by the
# application user before dropping privileges.
mkdir -p /app/downloads
chown -R appuser:appuser /app/downloads

# Run the application as the non-root user.
exec gosu appuser "$@"
