"""
Semantic Document Compressor (MAXIMALIST VERSION)
Combines:
1. Core Section enforcement (Fixes generic query context loss)
2. Programmatic Critical Rules (Fixes specific hallucinations)
3. Full keyword coverage (Restores original granular triggers)
"""

import re
from typing import List, Dict
from pathlib import Path


class SemanticCompressor:
    """
    Extracts relevant sections from semantic doc based on query keywords.
    Reduces prompt size while maintaining accuracy.
    """
    
    # ---------------------------------------------------------
    # 1. KEYWORD TRIGGERS
    # Mapping specific keywords to specific numbered sections
    # ---------------------------------------------------------
    SECTION_TRIGGERS = {
        'approval_time': {
            'keywords': [
                'approval time', 'approval duration', 'time to approve',
                'approval period', 'longest approval', 'shortest approval',
                'approved', 'approval', 'slowest', 'fastest approval',
                'how long to approve', 'approval speed', 'tat', 'turnaround'
            ],
            'sections': [6, 8]  # Section numbers from semantic doc
        },
        'pending_duration': {
            'keywords': [
                'pending', 'pending time', 'pending duration',
                'waiting', 'not approved', 'stuck', 'not yet approved',
                'awaiting approval', 'under review'
            ],
            'sections': [6]
        },
        'rejection_ratio': {
            'keywords': [
                'rejection', 'rejection rate', 'rejection ratio',
                'rejection to approval', 'worst vendor', 'best vendor',
                'rejected', 'reject', 'rejection performance'
            ],
            'sections': [8, 9]
        },
        'status_filtering': {
            'keywords': [
                'approved', 'rejected', 'pending', 'commented',
                'status', 'approval status', 'invoice status'
            ],
            'sections': [8]
        },
        # These are technically covered by CORE now, but kept for explicit matching logic
        'region_filtering': {
            'keywords': [
                'region', 'south', 'north', 'east', 'west',
                'zone', 'geographic', 'geography', 'city', 'state',
                'location-based', 'area'
            ],
            'sections': [2, 3, 7]
        },
        'vendor_analysis': {
            'keywords': [
                'vendor', 'supplier', 'created by', 'payee',
                'who created', 'which vendor'
            ],
            'sections': [2, 3, 7]
        },
        'account_analysis': {
            'keywords': [
                'account', 'customer', 'client', 'account name',
                'which account', 'account performance'
            ],
            'sections': [2, 3, 4, 7]
        },
        'warehouse_analysis': {
            'keywords': [
                'warehouse', 'facility', 'location', 'warehouse name',
                'which warehouse', 'where'
            ],
            'sections': [2, 3, 7]
        },
        'simple_aggregation': {
            'keywords': [
                'count', 'total', 'sum', 'average', 'avg',
                'how many', 'number of', 'amount', 'total amount',
                'invoice count', 'invoice amount', 'total invoices',
                # EXPANDED FINANCIAL TERMS
                'expense', 'expenses', 'spend', 'spending', 'cost', 'costs',
                'bill', 'bills', 'value', 'payment', 'payments', 'financial'
            ],
            'sections': [5]  # Monetary
        },
        'time_filtering': {
            'keywords': [
                'last month', 'last week', 'this month', 'this week',
                'yesterday', 'today', 'last year', 'time period',
                'date range', 'between dates', 'last 6 months', 'last 3 months',
                'july', 'august', 'september', 'october', 'november', 'december',
                'january', 'february', 'march', 'april', 'may', 'june',
                'period from', 'inconsistent', 'missing months', 'which months',
                '2025', '2026', 'when'
            ],
            'sections': [10]
        },
        'comparative_analysis': {
            'keywords': [
                'compare', 'comparison', 'versus', 'vs', 'more than',
                'less than', 'higher than', 'lower than', 'better than',
                'worse than', 'performance',
                # EXPANDED RANKING TERMS
                'highest', 'lowest', 'most', 'least', 'top', 'bottom', 'rank'
            ],
            'sections': [9]
        },
        'temporal_gaps': {
            'keywords': [
                'missing', 'gap', 'inconsistent', 'not uploaded', 'absent',
                'missing months', 'gap in', 'not consistently', 'haven\'t uploaded',
                'which months', 'missing data', 'incomplete'
            ],
            'sections': [2, 3, 10]
        },
        'expense_category': {
        'keywords': [
            'rent', 'manpower', 'security', 'electricity', 'diesel',
            'courier', 'transport', 'mhe', 'insurance', 'tyre',
            'fuel', 'maintenance', 'repair', 'water', 'internet'
        ],
        'sections': [12] 
    }

    }
    
    def __init__(self, semantic_doc_path: Path):
        """
        Args:
            semantic_doc_path: Path to semantic_doc.md
        """
        if not semantic_doc_path.exists():
            raise FileNotFoundError(f"Semantic doc not found: {semantic_doc_path}")
        
        self.full_doc = semantic_doc_path.read_text(encoding='utf-8')
        self.sections = self._parse_sections()
        
        # ---------------------------------------------------------
        # 2. CORE SECTIONS (The "Safety Net")
        # These are ALWAYS included to prevent context loss.
        # ---------------------------------------------------------
        # 1: Global Conventions
        # 2: Terminology (Defines Account/Vendor) -> CRITICAL FIX
        # 3: Service Semantics (Defines Invoice/Warehouse Tables) -> CRITICAL FIX
        # 4: Join Policy
        # 5: Monetary Rules
        # 7: Name Matching
        # 11: Schema Integrity
        self.core_sections = [1, 2, 3, 4, 5, 7, 11]  
    
    def _parse_sections(self) -> Dict[int, str]:
        """Parse semantic doc into numbered sections."""
        sections = {}
        current_section_num = 0
        current_content = []
        
        for line in self.full_doc.split('\n'):
            # Detect section headers like "6. PENDING & APPROVAL SEMANTICS"
            match = re.match(r'^(\d+)\.\s+(.+)$', line.strip())
            
            if match:
                # Save previous section
                if current_section_num > 0:
                    sections[current_section_num] = '\n'.join(current_content)
                
                # Start new section
                current_section_num = int(match.group(1))
                current_content = [line]
            else:
                current_content.append(line)
        
        # Save last section
        if current_section_num > 0:
            sections[current_section_num] = '\n'.join(current_content)
        
        return sections
    
    def compress(self, question: str) -> str:
        """Extract only relevant sections based on question keywords."""
        question_lower = question.lower()
        
        # Start with CORE sections (The safety net)
        relevant_sections = set(self.core_sections)
        
        # Add triggered sections
        for category, config in self.SECTION_TRIGGERS.items():
            if any(keyword in question_lower for keyword in config['keywords']):
                relevant_sections.update(config['sections'])
        
        # OPTION C SAFETY: If query is too complex (>9 sections), use full doc
        if len(relevant_sections) > 9:
            # print(f"[Compression Skipped] Complex query needs {len(relevant_sections)} sections, using full doc")
            return self.full_doc
            
        # Build compressed doc
        compressed_parts = [
            "# EMS Semantic Documentation (Relevant Sections)",
            "Status: ACTIVE – AUTHORITATIVE",
            ""
        ]
        
        for section_num in sorted(relevant_sections):
            if section_num in self.sections:
                compressed_parts.append(self.sections[section_num])
                compressed_parts.append("")
        
        compressed = '\n'.join(compressed_parts)
        
        return compressed
    
    def get_critical_rules_for_query(self, question: str) -> List[str]:
        """
        Extract critical rules as bullet points for prompt emphasis.
        Combines ORIGINAL rules with NEW Programmatic Constraints.
        """
        question_lower = question.lower()
        rules = []
        
        # --- 1. NEW: VENDOR IDENTITY RULE (Fixes 'quick_code_master' hallucination) ---
        if any(kw in question_lower for kw in ['vendor', 'supplier', 'payee']):
            rules.append("VENDOR IDENTITY: Vendors are USERS, NOT Quick Codes.")
            rules.append("JOIN: JOIN `ems-auth-service`.`user` u ON invoice_info.vendor_id = u.id")
            rules.append("SELECT: u.full_name (as Vendor Name)")

        # --- 2. NEW: SPEND/MONETARY RULE (Fixes 'line_items' hallucination) ---
        financial_terms = ['spend', 'amount', 'cost', 'total', 'bill', 'expense', 'value']
        if any(kw in question_lower for kw in financial_terms):
            rules.append("MONETARY SOURCE: Use `invoice_info`.`total_amount` ONLY.")
            rules.append("PROHIBITED: Do NOT sum `invoice_line_items` columns.")
            rules.append("PROHIBITED: Do NOT use `invoice_line_items_expense` table.")

        # --- 3. ORIGINAL: Approval time rules ---
        if any(kw in question_lower for kw in ['approval time', 'approval duration', 'approved', 'tat', 'turnaround']):
            rules.append("Approval time = updated_at - created_at (NEVER use NOW())")
            rules.append("MUST join master_status for status filtering")
            rules.append("Use TIMESTAMPDIFF or DATEDIFF for time calculations")
        
        # --- 4. ORIGINAL: Status filtering rules ---
        if any(kw in question_lower for kw in ['approved', 'rejected', 'pending', 'status']):
            rules.append("approval_status MUST be resolved via master_status.name")
            rules.append("NEVER use numeric approval_status values")
            rules.append("Use: LOWER(ms.name) LIKE LOWER('%status%')")
        
        # --- 5. ORIGINAL: Ratio rules ---
        if any(kw in question_lower for kw in ['ratio', 'rate', 'rejection', 'approval']):
            rules.append("Ratio denominator = COUNT(all invoices), not filtered count")
            rules.append("Use NULLIF to guard against division by zero")
        
        # --- 6. ORIGINAL: Region rules ---
        if any(kw in question_lower for kw in ['region', 'south', 'north', 'east', 'west']):
            rules.append("Region comes from warehouse_info.region_id → quick_code_master")
            rules.append("NOT from account_info.state_id")
        
        # --- 7. ORIGINAL: Missing/gap queries ---
        if any(kw in question_lower for kw in ['missing', 'gap', 'inconsistent', 'not uploaded', 'haven\'t']):
            rules.append("Missing data requires CTE to generate expected values, then LEFT JOIN to find gaps")
            rules.append("Cannot use HAVING COUNT = 0 for absence - no rows means nothing to count")

        if any(kw in question_lower for kw in ['month', 'monthly', 'trend', 'over time']):
            rules.append("TIME CONSISTENCY: Filter AND Group by `invoice_month`.")
            rules.append("PROHIBITED: Do not filter by `invoice_date` if grouping by `invoice_month`.")

        time_match = re.search(r'last (\d+) months?', question_lower)
        if time_match:
            months = time_match.group(1)
            rules.append(f"CALENDAR TIME: 'Last {months} months' means {months} FULL COMPLETED months.")
            rules.append(f"START DATE: DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL {months} MONTH), '%Y-%m-01')")
            rules.append("END DATE: DATE_FORMAT(CURDATE(), '%Y-%m-01') (Strictly excludes current partial month)")
            rules.append("FILTER COLUMN: Use `invoice_month` (Bill Date), NOT `invoice_date`.")
        
        if any(kw in question_lower for kw in ['month', 'monthly', 'trend', 'over time']):
            rules.append("TIME CONSISTENCY: Filter AND Group by `invoice_month`.")

        
        return rules


# Convenience function for easy import
def compress_semantic_doc(question: str, semantic_doc_path: Path) -> str:
    """
    Convenience function to compress semantic doc for a question.
    """
    compressor = SemanticCompressor(semantic_doc_path)
    return compressor.compress(question)