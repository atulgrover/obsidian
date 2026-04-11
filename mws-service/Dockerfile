FROM node:20-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Initialize MWS project using the official create tool
RUN npx @tiddlywiki/create-mws@latest mws-data && \
    cd mws-data && \
    npx mws init-store --admin-password "1234" || true

# Copy the initialized data to /data for volume mount
RUN cp -r /app/mws-data /data

# Install better-sqlite3 for auto-login helper
RUN npm init -y && npm install better-sqlite3

# Copy auto-login helper
COPY auto-login.js /app/auto-login.js

EXPOSE 8080 8081

VOLUME ["/data/store"]

HEALTHCHECK --interval=15s --timeout=10s --retries=10 --start-period=30s \
    CMD curl -f http://localhost:8080/ || exit 1

WORKDIR /data
CMD npx mws listen --listener host=0.0.0.0 port=8080 & node /app/auto-login.js