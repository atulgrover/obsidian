FROM python:3.11-slim

WORKDIR /app

# 1. Torch CPU first — must precede sentence-transformers so pip's dependency
#    resolver sees torch already satisfied and does NOT pull CUDA packages.
RUN pip install --no-cache-dir \
    torch \
    --index-url https://download.pytorch.org/whl/cpu

# 2. Everything else — sentence-transformers will reuse the torch above.
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    sentence-transformers

COPY app.py .

EXPOSE 8021

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8021"]
