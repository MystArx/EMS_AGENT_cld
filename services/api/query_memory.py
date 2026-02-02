import os
import json
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer


class QueryMemory:
    """
    FAISS-based semantic memory for query / chat history.
    - CPU-only
    - Persistent
    - No native build drama on Python 3.11
    """

    def __init__(self, path="data/query_memory"):
        os.makedirs(path, exist_ok=True)

        self.index_path = os.path.join(path, "index.faiss")
        self.data_path = os.path.join(path, "data.json")

        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
        self.dim = self.embedder.get_sentence_embedding_dimension()

        if os.path.exists(self.index_path) and os.path.exists(self.data_path):
            self.index = faiss.read_index(self.index_path)
            with open(self.data_path, "r") as f:
                self.data = json.load(f)
        else:
            # Inner product + normalized embeddings = cosine similarity
            self.index = faiss.IndexFlatIP(self.dim)
            self.data = []

    # -----------------------------
    # Step 2 — Recall
    # -----------------------------
    def recall(self, query: str, k: int = 3) -> list[str]:
        if not self.data:
            return []

        qvec = self.embedder.encode(
            query,
            normalize_embeddings=True
        ).astype("float32")

        scores, indices = self.index.search(
        np.array([qvec]),
        min(k, len(self.data))
        )

        return [self.data[i] for i in indices[0]]

    # -----------------------------
    # Step 3 — Write-back
    # -----------------------------
    def add(self, question: str, sql: str, result_summary: str):
        document = (
            f"QUESTION:\n{question}\n\n"
            f"SQL:\n{sql}\n\n"
            f"RESULT:\n{result_summary}"
        )

        vec = self.embedder.encode(
            document,
            normalize_embeddings=True
        ).astype("float32")

        self.index.add(np.array([vec]))
        self.data.append(document)

        faiss.write_index(self.index, self.index_path)
        with open(self.data_path, "w") as f:
            json.dump(self.data, f, indent=2)
