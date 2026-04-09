-- Migration: Add domain metadata + embedding columns to rag2_chunks
-- Run this on existing databases that were created before these columns existed.
-- Safe to run multiple times (IF NOT EXISTS / IF NOT EXISTS on indexes).

ALTER TABLE rag2_chunks ADD COLUMN IF NOT EXISTS doc_type TEXT;
ALTER TABLE rag2_chunks ADD COLUMN IF NOT EXISTS doc_date DATE;
ALTER TABLE rag2_chunks ADD COLUMN IF NOT EXISTS parties TEXT[];
ALTER TABLE rag2_chunks ADD COLUMN IF NOT EXISTS statutory_refs TEXT[];
ALTER TABLE rag2_chunks ADD COLUMN IF NOT EXISTS embedding vector(768);

CREATE INDEX IF NOT EXISTS rag2_chunks_doc_type_idx ON rag2_chunks (doc_type);
CREATE INDEX IF NOT EXISTS rag2_chunks_doc_date_idx ON rag2_chunks (doc_date);
CREATE INDEX IF NOT EXISTS rag2_chunks_embedding_hnsw_idx ON rag2_chunks USING hnsw (embedding vector_cosine_ops);