#!/usr/bin/env python3
"""
Test script to verify enhanced SQL generation system.
Run this after migration to ensure everything works.
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.api.sql_client import SQLClient




def test_basic_generation():
    """Test 1: Basic SQL generation"""
    print("\n" + "="*60)
    print("TEST 1: Basic SQL Generation")
    print("="*60)
    
    client = SQLClient()
    
    question = "What is the approval time in days for the invoice with the longest approval time?"
    print(f"\nQuestion: {question}")
    
    sql = client.generate_sql(question)
    
    print(f"\nGenerated SQL:")
    print(sql)
    
    # Check for correctness
    checks = {
        'Has updated_at': 'updated_at' in sql.lower(),
        'Has master_status': 'master_status' in sql.lower(),
        'No NOW()': 'NOW()' not in sql.upper(),
        'Uses LIKE for status': 'LIKE' in sql.upper()
    }
    
    print("\n✓ Validation Checks:")
    for check, passed in checks.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {check}")
    
    all_passed = all(checks.values())
    return all_passed

def test_golden_query_system():
    """Test 2: Golden query pattern matching"""
    print("\n" + "="*60)
    print("TEST 2: Golden Query System")
    print("="*60)
    
    client = SQLClient()
    
    # This should match the default golden query
    question = "What is the approval time in days for the invoice with the longest approval time?"
    
    print(f"\nQuestion: {question}")
    print("Expected: Should find similar example and learn pattern")
    
    sql = client.generate_sql(question)
    
    # Check golden stats
    stats = client.get_golden_stats()
    print(f"\n✓ Golden Query Stats:")
    print(f"  Total examples: {stats['total_examples']}")
    print(f"  Embeddings enabled: {stats['embeddings_enabled']}")
    print(f"  Categories: {stats.get('tags', [])}")
    
    return stats['total_examples'] >= 3

def test_compression():
    """Test 3: Semantic compression"""
    print("\n" + "="*60)
    print("TEST 3: Semantic Compression")
    print("="*60)
    
    from pathlib import Path
    from services.api.semantic_compressor import SemanticCompressor
    
    semantic_path = Path("data/semantic/semantic_doc.md")
    
    if not semantic_path.exists():
        print("✗ Semantic doc not found")
        return False
    
    compressor = SemanticCompressor(semantic_path)
    
    # Test compression on different query types
    test_queries = [
        "What is the approval time in days?",
        "Which vendor has most rejected invoices in South region?",
        "Show me pending invoices"
    ]
    
    print("\n✓ Compression Tests:")
    for query in test_queries:
        compressed = compressor.compress(query)
        original_size = len(compressor.full_doc)
        compressed_size = len(compressed)
        reduction = ((original_size - compressed_size) / original_size) * 100
        
        print(f"\n  Query: {query[:50]}...")
        print(f"  Original: {original_size} chars")
        print(f"  Compressed: {compressed_size} chars")
        print(f"  Reduction: {reduction:.1f}%")
    
    return True

def test_validation():
    """Test 4: SQL validation"""
    print("\n" + "="*60)
    print("TEST 4: SQL Validator")
    print("="*60)
    
    from services.api.sql_validator import SQLValidator
    
    validator = SQLValidator()
    
    # Test bad SQL
    bad_sql = """
    SELECT DATEDIFF(NOW(), ii.created_at) AS approval_time
    FROM invoice_info ii
    WHERE ii.approval_status = 2
    """
    
    question = "What is the approval time?"
    
    violations = validator.validate(bad_sql, question)
    
    print(f"\n✓ Testing validation on bad SQL:")
    print(f"  Found {len(violations)} violations:")
    for v in violations:
        print(f"    - {v.rule}: {v.description}")
    
    return len(violations) > 0  # Should find violations

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("ENHANCED SQL GENERATION SYSTEM - TEST SUITE")
    print("="*60)
    
    tests = [
        ("Basic Generation", test_basic_generation),
        ("Golden Query System", test_golden_query_system),
        ("Semantic Compression", test_compression),
        ("SQL Validation", test_validation)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n✗ Test '{name}' failed with error: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n✓ All tests passed! System is ready.")
        return 0
    else:
        print("\n✗ Some tests failed. Check output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())