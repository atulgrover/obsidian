"""
InLegal-SBERT — OpenAI-compatible embeddings endpoint

GET  /health
POST /v1/embeddings   {"input": "text" | ["text", ...], "model": "..."}
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Union
from sentence_transformers import SentenceTransformer
import os

MODEL_NAME = os.getenv("SBERT_MODEL", "bhavyagiri/InLegal-Sbert")

app = FastAPI(title="InLegal-SBERT Embeddings", version="1.0.0")

print(f"Loading model: {MODEL_NAME}")
model = SentenceTransformer(MODEL_NAME)
print("Model loaded.")


class EmbeddingRequest(BaseModel):
    input: Union[str, List[str]]
    model: str = "inlegal-sbert"


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/v1/embeddings")
def embeddings(req: EmbeddingRequest):
    texts = [req.input] if isinstance(req.input, str) else req.input
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return {
        "object": "list",
        "model": req.model,
        "data": [
            {"object": "embedding", "index": i, "embedding": vec.tolist()}
            for i, vec in enumerate(vecs)
        ],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }
