FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "lightrag-hku[postgres]" \
    fastapi \
    uvicorn[standard] \
    httpx \
    psycopg2-binary \
    python-frontmatter

COPY app.py .

EXPOSE 8020

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8020"]
