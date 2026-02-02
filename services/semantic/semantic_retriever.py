import faiss
import json
import numpy as np
import requests

OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"

index = faiss.read_index("semantic.index")
chunks = json.loads(open("semantic_chunks.json").read())


def embed(text: str) -> list[float]:
    resp = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def retrieve_relevant_semantics(query: str, k: int = 3) -> list[str]:
    vec = np.array([embed(query)]).astype("float32")
    _, idxs = index.search(vec, k)
    return [chunks[i] for i in idxs[0]]
