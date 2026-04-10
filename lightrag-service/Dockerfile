FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "lightrag-hku[postgres,api]" \
    uvicorn[standard]

# Patch: EmbeddingFunc.result.size fails when HTTP embedders return lists not numpy arrays.
# Convert result to numpy array before calling .size so both list and ndarray work.
RUN sed -i \
    's/result = await self\.func(\*args, \*\*kwargs)/result = await self.func(*args, **kwargs)\n        import numpy as _np\n        if not hasattr(result, "size"): result = _np.array(result, dtype=_np.float32)/' \
    /usr/local/lib/python3.11/site-packages/lightrag/utils.py

EXPOSE 8020

CMD ["python", "-m", "lightrag.api.lightrag_server", \
     "--host", "0.0.0.0", \
     "--port", "8020", \
     "--input-dir", "/data/input"]
