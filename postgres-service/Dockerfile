FROM apache/age:release_PG16_1.6.0

USER root

# pgvector — install pre-built package from PGDG repo (already configured in base image)
# This avoids needing postgresql-server-dev headers for a source build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

USER postgres
