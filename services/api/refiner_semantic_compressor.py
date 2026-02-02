"""
Refiner Semantic Compressor
Compresses business_semantic.md for Groq refiner based on query keywords.

This is SEPARATE from semantic_compressor.py which handles semantic_doc.md.
"""

import re
from pathlib import Path
from typing import Set


class RefinerSemanticCompressor:
    """
    Compresses business_semantic.md based on query keywords.
    Unlike semantic_compressor.py, this handles markdown with ## headers (no numbers).
    """
    
    # Map query keywords to semantic section headers
    SECTION_TRIGGERS = {
        'vendor': {'vendor', 'supplier', 'payee'},
        'account': {'account', 'customer', 'client'},
        'warehouse': {'warehouse', 'facility', 'location'},
        'city': {'city', 'cities'},
        'region': {'region', 'zone', 'north', 'south', 'east', 'west'},
        'approval_time': {'approval time', 'approval duration', 'tat', 'turnaround'},
        'pending': {'pending', 'stuck', 'awaiting'},
        'metric': {'metric', 'expense', 'total expense', 'invoice amount'},
        'time': {'last month', 'last week', 'yesterday', 'today', 'time semantic'},
        'follow_up': {'which', 'that', 'those', 'this', 'he', 'she', 'they'},
        'projection': {
            'list', 'names', 'name', 'show', 'details',
            'break down', 'give me', 'display'
        },
        'attribute': {'remarks', 'comments', 'notes', 'attribute'},
        'missing': {'missing', 'gap', 'inconsistent', 'not uploaded', 'absent', 'haven\'t'}
    }

    
    # These sections are ALWAYS included (critical for all queries)
    CORE_SECTIONS = {
        'output discipline',
        'name matching semantics',
        'corrections',
        'follow-up query handling',  # NEW - always include for context awareness
        'result context awareness'   # NEW - always include
    }
    
    def __init__(self, semantic_file_path: Path):
        """
        Args:
            semantic_file_path: Path to business_semantic.md
        """
        if not semantic_file_path.exists():
            raise FileNotFoundError(f"Refiner semantic file not found: {semantic_file_path}")
        
        self.full_doc = semantic_file_path.read_text(encoding='utf-8')
        self.sections = self._parse_sections()
    
    def _parse_sections(self) -> dict[str, str]:
        """
        Parse business_semantic.md into sections by ## headers.
        
        Returns:
            Dict mapping section header (lowercase) to section content
        """
        sections = {}
        
        # Split by ## headers
        parts = re.split(r'^##\s+', self.full_doc, flags=re.MULTILINE)
        
        for part in parts[1:]:  # Skip first (before any ##)
            if not part.strip():
                continue
            
            # First line is the header
            lines = part.split('\n', 1)
            header = lines[0].strip().lower()
            content = lines[1] if len(lines) > 1 else ""
            
            sections[header] = f"## {lines[0]}\n{content}"
        
        return sections
    
    def compress(self, question: str) -> str:
        """
        Extract relevant sections based on question keywords.
        
        Args:
            question: The user's query
            
        Returns:
            Compressed semantic doc with only relevant sections
        """
        question_lower = question.lower()
        
        # Start with core sections
        sections_to_include = set(self.CORE_SECTIONS)
        
        # Add sections based on keywords
        for category, keywords in self.SECTION_TRIGGERS.items():
            if any(keyword in question_lower for keyword in keywords):
                sections_to_include.add(category)
        
        # Build compressed doc
        compressed_parts = []
        
        for section_header, section_content in self.sections.items():
            # Check if this section should be included
            should_include = False
            
            # Check against core sections
            for core in sections_to_include:
                if core in section_header:
                    should_include = True
                    break
            
            if should_include:
                compressed_parts.append(section_content)
        
        compressed = "\n\n".join(compressed_parts)
        
        # Fallback: if nothing matched, return full doc
        if not compressed or len(compressed) < 500:
            return self.full_doc
        
        # Log compression stats
        original_size = len(self.full_doc)
        compressed_size = len(compressed)
        reduction = ((original_size - compressed_size) / original_size) * 100
        
        print(f"[Refiner Compression] {original_size} → {compressed_size} chars ({reduction:.1f}% reduction)")
        
        return compressed
    
    def get_critical_rules(self, question: str) -> list[str]:
        """
        Extract critical rules to highlight at top of prompt.
        
        Args:
            question: The user's query
            
        Returns:
            List of critical rule strings
        """
        question_lower = question.lower()
        rules = []
        
        # Follow-up handling
        if any(word in question_lower for word in ['which', 'that', 'those', 'this', 'he', 'she']):
            rules.append("If user says 'which', 'that', or pronoun: they may be referencing previous results")
        
        # Missing/gap queries
        if any(word in question_lower for word in ['missing', 'gap', 'inconsistent', 'not uploaded', 'haven\'t']):
            rules.append("'Missing' or 'gap' queries require special temporal analysis")
        
        # Name matching
        if any(word in question_lower for word in ['vendor', 'account', 'warehouse']):
            rules.append("All entity names use fuzzy matching (LIKE), never exact match")
        
        return rules


# Convenience function
def compress_refiner_semantics(question: str, semantic_path: Path) -> str:
    """
    Convenience function to compress refiner semantics.
    
    Args:
        question: The user's query
        semantic_path: Path to business_semantic.md
        
    Returns:
        Compressed semantic documentation
    """
    compressor = RefinerSemanticCompressor(semantic_path)
    return compressor.compress(question)