FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create vault directory
RUN mkdir -p /vault

EXPOSE 5004

ENV VAULT_ROOT=/vault

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5004"]