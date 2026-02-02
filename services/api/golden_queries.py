"""
Golden Query System with RAG (Retrieval-Augmented Generation)
Learns patterns from corrected queries using semantic similarity.
"""

import json
import os
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    print("WARNING: sentence-transformers not installed. Golden queries will use exact matching only.")
    print("Install with: pip install sentence-transformers")


@dataclass
class GoldenExample:
    """A known-correct question→SQL pair with metadata."""
    question: str
    sql: str
    notes: str = ""
    tags: List[str] = None  # e.g., ['approval_time', 'region_filtering']
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class GoldenQuerySystem:
    """
    RAG-based golden query system.
    Learns patterns from examples using semantic similarity.
    """
    
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        model_name: str = "all-MiniLM-L6-v2"
    ):
        """
        Args:
            storage_path: Path to golden_queries.json (auto-created if missing)
            model_name: Sentence transformer model (default is 22MB, CPU-friendly)
        """
        # Setup storage
        if storage_path is None:
            storage_path = Path("data/golden_queries/golden_queries.json")
        
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Setup embeddings
        self.encoder = None
        self.embeddings_matrix = None
        
        if EMBEDDINGS_AVAILABLE:
            try:
                print(f"[Golden Queries] Loading embedding model: {model_name}")
                self.encoder = SentenceTransformer(model_name)
                print("[Golden Queries] Embedding model loaded successfully")
            except Exception as e:
                print(f"[Golden Queries] Failed to load embeddings: {e}")
                self.encoder = None
        
        # Load examples
        self.examples: List[GoldenExample] = []
        self._load()
    
    def _load(self):
        """Load golden examples from JSON."""
        if not self.storage_path.exists():
            print(f"[Golden Queries] No existing data found. Starting fresh.")
            self._initialize_with_defaults()
            return
        
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.examples = [
                GoldenExample(**item) for item in data.get('examples', [])
            ]
            
            print(f"[Golden Queries] Loaded {len(self.examples)} golden examples")
            
            # Rebuild embeddings if encoder available
            if self.encoder:
                self._rebuild_embeddings()
                
        except Exception as e:
            print(f"[Golden Queries] Error loading: {e}")
            self._initialize_with_defaults()
    
    def _save(self):
        """Save golden examples to JSON."""
        data = {
            'examples': [
                {
                    'question': ex.question,
                    'sql': ex.sql,
                    'notes': ex.notes,
                    'tags': ex.tags
                }
                for ex in self.examples
            ]
        }
        
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"[Golden Queries] Saved {len(self.examples)} examples to {self.storage_path}")
    
    def _initialize_with_defaults(self):
        """Initialize with a few critical examples."""
        defaults = [
            GoldenExample(
                question="What is the approval time in days for the invoice with the longest approval time?",
                sql="""SELECT 
    ii.id,
    DATEDIFF(ii.updated_at, ii.created_at) AS approval_time_in_days
FROM `ems-portal-service`.`invoice_info` ii
JOIN `ems-portal-service`.`master_status` ms ON ii.approval_status = ms.id
WHERE LOWER(ms.name) LIKE LOWER('%approved%')
ORDER BY approval_time_in_days DESC
LIMIT 1""",
                notes="Approval time = updated_at - created_at. Never use NOW(). Must join master_status.",
                tags=['approval_time', 'status_filtering']
            ),
            GoldenExample(
                question="Which vendor has the worst rejection to approval ratio in the South region?",
                sql="""SELECT 
    u.full_name AS vendor_name,
    SUM(CASE WHEN LOWER(ms.name) LIKE LOWER('%rejected%') THEN 1 ELSE 0 END) * 1.0 / 
    NULLIF(SUM(CASE WHEN LOWER(ms.name) LIKE LOWER('%approved%') THEN 1 ELSE 0 END), 0) AS rejection_to_approval_ratio
FROM `ems-portal-service`.`invoice_info` ii
JOIN `ems-auth-service`.`user` u ON ii.created_by = u.id
JOIN `ems-portal-service`.`master_status` ms ON ii.approval_status = ms.id
JOIN `ems-warehouse-service`.`warehouse_info` wi ON ii.warehouse_id = wi.id
JOIN `ems-portal-service`.`quick_code_master` qcm ON wi.region_id = qcm.id
WHERE LOWER(qcm.name) LIKE LOWER('%south%')
GROUP BY u.full_name
HAVING SUM(CASE WHEN LOWER(ms.name) LIKE LOWER('%approved%') THEN 1 ELSE 0 END) > 0
ORDER BY rejection_to_approval_ratio DESC
LIMIT 1""",
                notes="Ratio = rejected / approved. Region via warehouse→region_id. Must join master_status.",
                tags=['rejection_ratio', 'region_filtering', 'vendor_analysis']
            ),
            GoldenExample(
                question="What is the average approval time in hours for approved invoices?",
                sql="""SELECT 
    AVG(TIMESTAMPDIFF(HOUR, ii.created_at, ii.updated_at)) AS avg_approval_hours
FROM `ems-portal-service`.`invoice_info` ii
JOIN `ems-portal-service`.`master_status` ms ON ii.approval_status = ms.id
WHERE LOWER(ms.name) LIKE LOWER('%approved%')""",
                notes="Use TIMESTAMPDIFF(HOUR, ...) for hours. Same pattern: updated_at - created_at.",
                tags=['approval_time', 'status_filtering']
            )
        ]
        
        self.examples = defaults
        self._save()
        
        if self.encoder:
            self._rebuild_embeddings()
    
    def _rebuild_embeddings(self):
        """Rebuild embedding matrix for all examples."""
        if not self.encoder or not self.examples:
            return
        
        print("[Golden Queries] Building embeddings...")
        questions = [ex.question for ex in self.examples]
        self.embeddings_matrix = self.encoder.encode(
            questions,
            convert_to_tensor=False,
            show_progress_bar=False
        )
        print(f"[Golden Queries] Embeddings ready for {len(self.examples)} examples")
    
    def find_similar(
        self,
        question: str,
        top_k: int = 1,
        threshold: float = 0.55
    ) -> List[Tuple[GoldenExample, float]]:
        """
        Find similar golden examples using semantic search.
        
        Args:
            question: The refined analytical question
            top_k: Number of examples to return (default: 1 for token efficiency)
            threshold: Minimum similarity score 0-1 (default: 0.55)
            
        Returns:
            List of (example, similarity_score) tuples, sorted by similarity
        """
        if not self.examples:
            return []
        
        # Exact match first (fastest)
        for ex in self.examples:
            if ex.question.lower() == question.lower():
                print(f"[Golden Queries] Exact match found!")
                return [(ex, 1.0)]
        
        # Semantic search if embeddings available
        if self.encoder and self.embeddings_matrix is not None:
            return self._semantic_search(question, top_k, threshold)
        
        # Fallback: keyword-based matching
        return self._keyword_search(question, top_k)
    
    def _semantic_search(
        self,
        question: str,
        top_k: int,
        threshold: float
    ) -> List[Tuple[GoldenExample, float]]:
        """Semantic similarity search using embeddings."""
        # Encode query
        query_embedding = self.encoder.encode(
            question,
            convert_to_tensor=False,
            show_progress_bar=False
        )
        
        # Compute cosine similarities
        similarities = np.dot(self.embeddings_matrix, query_embedding) / (
            np.linalg.norm(self.embeddings_matrix, axis=1) * 
            np.linalg.norm(query_embedding)
        )
        
        # Get top-k
        top_indices = np.argsort(similarities)[::-1][:top_k]
        
        results = []
        for idx in top_indices:
            score = float(similarities[idx])
            if score >= threshold:
                results.append((self.examples[idx], score))
                print(f"[Golden Queries] Similar example found (score: {score:.3f})")
        
        return results
    
    def _keyword_search(
        self,
        question: str,
        top_k: int
    ) -> List[Tuple[GoldenExample, float]]:
        """Fallback: simple keyword-based matching."""
        question_words = set(question.lower().split())
        
        scores = []
        for ex in self.examples:
            ex_words = set(ex.question.lower().split())
            overlap = len(question_words & ex_words)
            score = overlap / max(len(question_words), len(ex_words))
            scores.append((ex, score))
        
        # Sort by score and return top_k
        scores.sort(key=lambda x: x[1], reverse=True)
        
        results = [(ex, score) for ex, score in scores[:top_k] if score > 0.3]
        
        if results:
            print(f"[Golden Queries] Keyword match found (score: {results[0][1]:.3f})")
        
        return results
    
    def add_example(
        self,
        question: str,
        sql: str,
        notes: str = "",
        tags: List[str] = None
    ):
        """
        Add a new golden example.
        
        Args:
            question: The refined analytical question
            sql: The correct SQL
            notes: Explanation of why this SQL is correct
            tags: Category tags for organization
        """
        # Check for duplicates
        for ex in self.examples:
            if ex.question.lower() == question.lower():
                print(f"[Golden Queries] Updating existing example")
                ex.sql = sql
                ex.notes = notes
                if tags:
                    ex.tags = tags
                self._save()
                if self.encoder:
                    self._rebuild_embeddings()
                return
        
        # Add new
        example = GoldenExample(
            question=question,
            sql=sql,
            notes=notes,
            tags=tags or []
        )
        
        self.examples.append(example)
        self._save()
        
        if self.encoder:
            self._rebuild_embeddings()
        
        print(f"[Golden Queries] Added new example. Total: {len(self.examples)}")
    
    def get_stats(self) -> Dict:
        """Get statistics about the golden query system."""
        return {
            'total_examples': len(self.examples),
            'embeddings_enabled': self.encoder is not None,
            'storage_path': str(self.storage_path),
            'tags': list(set(tag for ex in self.examples for tag in ex.tags))
        }