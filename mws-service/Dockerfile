FROM node:20-slim

WORKDIR /app

# Install tiddlywiki and MWS
RUN npm install -g tiddlywiki@latest

# Create data directory
RUN mkdir -p /data/store

# Initialize MWS store on first run via entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

VOLUME ["/data/store"]

ENTRYPOINT ["/entrypoint.sh"]