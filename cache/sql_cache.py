import json
import os
import time
import hashlib
import re
from typing import Optional

CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def normalize_question(q: str) -> str:
    q = q.lower()
    q = re.sub(r"[^\w\s]", "", q)
    q = re.sub(r"\s+", " ", q)
    return q.strip()


class SQLCache:
    def __init__(self, path: str = "data/cache/sql_cache.json"):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}
        else:
            self.cache = {}

    def _persist(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2)

    def _key(self, question: str) -> str:
        norm = normalize_question(question)
        return hashlib.sha256(norm.encode()).hexdigest()

    def get(self, question: str) -> Optional[str]:
        key = self._key(question)
        entry = self.cache.get(key)
        if not entry:
            return None

        if time.time() - entry["ts"] > CACHE_TTL_SECONDS:
            self.cache.pop(key, None)
            self._persist()
            return None

        return entry["sql"]

    def set(self, question: str, sql: str):
        key = self._key(question)
        self.cache[key] = {
            "sql": sql,
            "ts": time.time()
        }
        self._persist()
