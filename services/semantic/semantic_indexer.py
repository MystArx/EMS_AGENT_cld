from pathlib import Path
import faiss
import numpy as np
import requests
import json

SEMANTIC_PATH = Path("data/semantic/business_semantic.md")
OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"


def embed(text: str) -> list[float]:
    resp = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def chunk_semantics(text: str) -> list[str]:
    chunks = []
    current = []

    for line in text.splitlines():
        if line.strip().startswith("###") and current:
            chunks.append("\n".join(current).strip())
            current = []
        current.append(line)

    if current:
        chunks.append("\n".join(current).strip())

    return [c for c in chunks if len(c.split()) > 10]


def build_index():
    text = SEMANTIC_PATH.read_text()
    chunks = chunk_semantics(text)

    embeddings = [embed(c) for c in chunks]
    dim = len(embeddings[0])

    index = faiss.IndexFlatL2(dim)
    index.add(np.array(embeddings).astype("float32"))

    return index, chunks


if __name__ == "__main__":
    index, chunks = build_index()
    faiss.write_index(index, "semantic.index")
    Path("semantic_chunks.json").write_text(json.dumps(chunks, indent=2))
