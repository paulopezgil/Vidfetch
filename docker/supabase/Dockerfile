FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

ARG SUPABASE_VERSION=3.2.0
ARG DOCKER_CLI_VERSION=27.3.1

# The Supabase CLI shells out to the Docker CLI for health/inspection calls, so
# include the static client. The Docker daemon is provided by the host socket.
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
        x86_64|amd64) docker_arch="x86_64" ;; \
        aarch64|arm64) docker_arch="aarch64" ;; \
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL \
        "https://download.docker.com/linux/static/stable/${docker_arch}/docker-${DOCKER_CLI_VERSION}.tgz" \
        -o /tmp/docker.tgz; \
    tar -xzf /tmp/docker.tgz -C /tmp; \
    install -m 0755 /tmp/docker/docker /usr/local/bin/docker; \
    rm -rf /tmp/docker /tmp/docker.tgz; \
    docker --version

# The Supabase CLI is a glibc-linked Go binary, so this image intentionally
# uses Debian rather than Alpine. The CLI talks to the mounted Docker socket
# through the Docker API; a separate docker CLI binary is not required.
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
        x86_64|amd64) asset="supabase_linux_amd64.tar.gz" ;; \
        aarch64|arm64) asset="supabase_linux_arm64.tar.gz" ;; \
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL \
        "https://github.com/supabase/cli/releases/download/v${SUPABASE_VERSION}/${asset}" \
        -o /tmp/supabase.tar.gz; \
    tar -xzf /tmp/supabase.tar.gz -C /usr/local/bin supabase; \
    rm /tmp/supabase.tar.gz; \
    supabase --version

COPY entrypoint.sh /usr/local/bin/supabase-entrypoint.sh
RUN chmod +x /usr/local/bin/supabase-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/supabase-entrypoint.sh"]
