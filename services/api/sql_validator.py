"""
SQL Validator (FIXED)
Post-generation validation with specific feedback for retry attempts.
Acts as a safety net to catch semantic violations.

FIXED: Backtick validation now works correctly
"""

import re
from typing import List, Dict
from dataclasses import dataclass

_TABLE_REF_RE = re.compile(
    r"`([^`]+)`\.`([^`]+)`",  # matches `schema`.`table`
    re.IGNORECASE
)


@dataclass
class Violation:
    """Represents a semantic violation in generated SQL."""
    rule: str
    description: str
    fix_hint: str


class SQLValidator:
    """
    Validates generated SQL against semantic rules.
    Provides specific feedback for LLM retry attempts.
    """

    def __init__(self, schema_json: dict | None = None):
        self.schema_json = schema_json or {}
        self.table_schema_map = _build_table_schema_map(self.schema_json)



    # Defines valid filters for different user roles
    ROLE_DEFINITIONS = {
        'vendor': {
            'keywords': ['vendor', 'supplier', 'payee'],
            'filter_logic': "user_type LIKE '%VENDOR%'"
        },
        'admin': {
            'keywords': ['admin', 'administrator', 'super user'],
            'filter_logic': "user_type LIKE '%ADMIN%'"
        },
        'staff': {
            'keywords': ['staff', 'employee', 'internal'],
            'filter_logic': "user_type LIKE '%EMPLOYEE%'"
        }
    }
    
    def validate(self, sql: str, question: str) -> List[Violation]:
        """
        Validate SQL against semantic rules.
        
        Args:
            sql: The generated SQL query
            question: The refined analytical question
            
        Returns:
            List of violations (empty if valid)
        """
        violations = []
        
        # Run all validation checks
        violations.extend(self._check_alias_syntax(sql))
        violations.extend(self._check_user_role_safety(sql, question))
        violations.extend(self._check_approval_time(sql, question))
        violations.extend(self._check_status_resolution(sql, question))
        violations.extend(self._check_region_resolution(sql, question))
        violations.extend(self._check_ratio_denominator(sql, question))
        violations.extend(self._check_schema_names(sql))
        violations.extend(self._check_master_status_join_integrity(sql))
        violations.extend(self._check_vendor_source(sql, question))
        violations.extend(self._check_spend_aggregation(sql, question))
        violations.extend(self._check_expense_category_resolution(sql,question))
        violations.extend(self._check_schema_integrity(sql))
        violations.extend(self._check_warehouse_source(sql))
        violations.extend(self._check_ambiguous_columns(sql))



        
        return violations
    
    def _check_user_role_safety(self, sql: str, question: str) -> List[Violation]:
        """Ensures that if a role is asked for, the user_type is filtered."""
        violations = []
        sql_lower = sql.lower()
        q_lower = question.lower()
        
        # Check if using user table
        uses_user_table = ('ems-auth-service' in sql_lower and 'user' in sql_lower)
        
        if not uses_user_table:
            # Error if asking for role but NOT using user table
            for role, config in self.ROLE_DEFINITIONS.items():
                if any(kw in q_lower for kw in config['keywords']):
                    violations.append(Violation(
                        rule="WRONG_TABLE_FOR_ROLE",
                        description=f"Queries for {role} must join `ems-auth-service`.`user`.",
                        fix_hint=f"JOIN `ems-auth-service`.`user` AND filter by {config['filter_logic']}"
                    ))
            return violations

        # Error if using user table but NOT filtering correctly
        for role, config in self.ROLE_DEFINITIONS.items():
            if any(kw in q_lower for kw in config['keywords']):
                if 'user_type' not in sql_lower:
                     violations.append(Violation(
                        rule=f"MISSING_{role.upper()}_FILTER",
                        description=f"You queried Users for '{role}' but forgot the type filter.",
                        fix_hint=f"Add condition: AND {config['filter_logic']}"
                    ))
                elif role not in sql_lower: 
                     violations.append(Violation(
                        rule=f"WRONG_TYPE_VALUE",
                        description=f"Filter seems to miss the specific '{role}' value.",
                        fix_hint=f"Ensure you use: {config['filter_logic']}"
                    ))
        return violations


    def _check_schema_integrity(self, sql: str) -> list[Violation]:
        """
        Ensure every `schema`.`table` reference matches MDL definition.
        """
        violations = []

        for schema, table in _TABLE_REF_RE.findall(sql):
            table_l = table.lower()
            schema_l = schema.lower()

            # Table not in MDL → ignore here (other validators may handle)
            if table_l not in self.table_schema_map:
                continue

            expected_schema = self.table_schema_map[table_l]

            if schema_l != expected_schema.lower():
                violations.append(Violation(
                    rule="WRONG_SCHEMA",
                    description=(
                        f"Table `{table}` is referenced from schema `{schema}`, "
                        f"but MDL defines it under `{expected_schema}`"
                    ),
                    fix_hint=(
                        f"Use `{expected_schema}`.`{table}` instead of `{schema}`.`{table}`"
                    )
                ))

        return violations



    def _check_alias_syntax(self, sql: str) -> List[Violation]:
        """Check for invalid aliases with spaces (e.g. AS Vendor Name)"""
        violations = []
        pattern = r'\bAS\s+([a-zA-Z0-9]+)\s+([a-zA-Z0-9]+)\b'
        matches = re.finditer(pattern, sql, re.IGNORECASE)
        for match in matches:
            bad_alias = f"{match.group(1)} {match.group(2)}"
            violations.append(Violation(
                rule="INVALID_ALIAS_SYNTAX",
                description=f"Aliases cannot contain spaces: '{bad_alias}'",
                fix_hint="Use snake_case (e.g., 'vendor_name') or remove spaces."
            ))
            break 
        return violations

    def _check_vendor_source(self, sql: str, question: str) -> List[Violation]:
        """Enforce Vendor = User table rule."""
        violations = []
        q_lower = question.lower()
        sql_lower = sql.lower()
        
        # If asking about Vendor...
        if any(kw in q_lower for kw in ['vendor', 'supplier', 'payee']):
            # ...MUST join user table
            if 'ems-auth-service' not in sql_lower or 'user' not in sql_lower:
                violations.append(Violation(
                    rule="WRONG_VENDOR_SOURCE",
                    description="Vendors must be queried from `ems-auth-service`.`user`",
                    fix_hint="JOIN `ems-auth-service`.`user` u ON invoice_info.vendor_id = u.id"
                ))
            
            # ...MUST NOT join quick_code_master for vendor names
            if 'quick_code_master' in sql_lower and 'vendor_name' in sql_lower:
                 violations.append(Violation(
                    rule="VENDOR_IS_NOT_QUICK_CODE",
                    description="Vendors are NOT Quick Codes.",
                    fix_hint="Remove quick_code_master join. Use `user`.`full_name`."
                ))
        return violations

    def _check_spend_aggregation(self, sql: str, question: str) -> List[Violation]:
        """Enforce Spend = invoice_info.total_amount rule."""
        violations = []
        q_lower = question.lower()
        sql_lower = sql.lower()
        
        financial_terms = ['spend', 'amount', 'cost', 'total', 'bill', 'expense']
        if any(kw in q_lower for kw in financial_terms):
            
            # Detect use of line_items for aggregation
            if 'invoice_line_items' in sql_lower:
                if not any(k in q_lower for k in ['expense', 'category', 'line item', 'item']):
                    violations.append(Violation(
                        rule="WRONG_SPEND_SOURCE",
                        description="Warehouse/account spend must be aggregated directly from invoice_info without line items",
                        fix_hint="Remove invoice_line_items joins and aggregate only invoice_info.total_amount"
                    ))

                
        return violations

    def _check_approval_time(self, sql: str, question: str) -> List[Violation]:
        """Validate approval time calculation rules."""
        violations = []
        
        # Check if this is an approval time query
        is_approval_query = any(
            term in question.lower()
            for term in ['approval time', 'approval duration', 'time to approve', 'approval period', 'tat', 'turnaround']
        )
        
        if not is_approval_query:
            return violations
        
        # Check for NOW() usage (forbidden)
        if re.search(r'\bNOW\s*\(\)', sql, re.IGNORECASE):
            violations.append(Violation(
                rule="APPROVAL_TIME_NOW_FORBIDDEN",
                description="NOW() must not be used in approval time calculations",
                fix_hint="Use: DATEDIFF(updated_at, created_at) or TIMESTAMPDIFF(unit, created_at, updated_at)"
            ))
        
        # Check for updated_at presence (required)
        if 'updated_at' not in sql.lower():
            violations.append(Violation(
                rule="APPROVAL_TIME_MISSING_UPDATED_AT",
                description="Approval time requires updated_at column",
                fix_hint="Approval time = updated_at - created_at (NOT NOW() - created_at)"
            ))
        
        # Check for master_status join (required for status filtering)
        if 'master_status' not in sql.lower():
            violations.append(Violation(
                rule="APPROVAL_TIME_MISSING_STATUS_JOIN",
                description="Approval queries must join master_status table",
                fix_hint="JOIN `ems-portal-service`.`master_status` ms ON ii.approval_status = ms.id"
            ))
        
        return violations
    
    def _check_status_resolution(self, sql: str, question: str) -> List[Violation]:
        """Validate status filtering rules."""
        violations = []
        
        # Check if query involves status filtering
        has_status = any(
            term in question.lower()
            for term in ['approved', 'rejected', 'pending', 'commented', 'status']
        )
        
        if not has_status:
            return violations
        
        # Check for numeric approval_status (forbidden)
        if re.search(r'approval_status\s*=\s*\d+', sql, re.IGNORECASE):
            violations.append(Violation(
                rule="STATUS_NUMERIC_FORBIDDEN",
                description="Numeric approval_status values are forbidden",
                fix_hint="Must join master_status and use: LOWER(ms.name) LIKE LOWER('%status_name%')"
            ))
        
        # Check for master_status join if not present
        if 'approval_status' in sql.lower() and 'master_status' not in sql.lower():
            violations.append(Violation(
                rule="STATUS_MISSING_MASTER_STATUS_JOIN",
                description="Status filtering requires master_status join",
                fix_hint="JOIN `ems-portal-service`.`master_status` ms ON ii.approval_status = ms.id"
            ))
        
        # Check for LIKE-based matching (preferred)
        if 'master_status' in sql.lower() and 'LIKE' not in sql.upper():
            violations.append(Violation(
                rule="STATUS_EXACT_MATCH_DISCOURAGED",
                description="Status matching should use LIKE for fuzzy matching",
                fix_hint="Use: LOWER(ms.name) LIKE LOWER('%status_name%') instead of exact equality"
            ))
        
        return violations
    
    def _check_region_resolution(self, sql: str, question: str) -> List[Violation]:
        """Validate region/geography resolution rules."""
        violations = []
        
        # Check if query involves region
        has_region = any(
            term in question.lower()
            for term in ['region', 'south', 'north', 'east', 'west', 'zone']
        )
        
        if not has_region:
            return violations
        
        # Check if using account geography instead of warehouse (common error)
        if 'account_info' in sql.lower() and 'warehouse_info' not in sql.lower():
            # Check if trying to get region from account
            if any(field in sql.lower() for field in ['state_id', 'city_id', 'zone_id']):
                violations.append(Violation(
                    rule="REGION_FROM_ACCOUNT_INVALID",
                    description="Region must come from warehouse, not account",
                    fix_hint="Join: invoice_info → warehouse_info → quick_code_master (via region_id)"
                ))
        
        return violations
    
    def _check_ratio_denominator(self, sql: str, question: str) -> List[Violation]:
        """Validate ratio/percentage calculation rules."""
        violations = []
        
        # Check if query involves ratios
        has_ratio = any(
            term in question.lower()
            for term in ['ratio', 'rate', 'percentage', 'rejection to approval']
        )
        
        if not has_ratio:
            return violations
        
        # Look for division in CASE statements
        # Common error: filtering denominator
        case_pattern = r'CASE\s+WHEN.*?END.*?/.*?CASE\s+WHEN.*?END'
        if re.search(case_pattern, sql, re.IGNORECASE | re.DOTALL):
            # Check if denominator uses <> (wrong pattern)
            if re.search(r'<>\s*\d+', sql):
                violations.append(Violation(
                    rule="RATIO_DENOMINATOR_FILTERED",
                    description="Ratio denominator should not be filtered by same condition",
                    fix_hint="Denominator = COUNT(id) or SUM(all cases). Example: rejected / approved, not rejected / (total - rejected)"
                ))
        
        return violations
    
    def _check_schema_names(self, sql: str) -> List[Violation]:
        """
        Validate schema naming conventions.
        FIXED: Properly detects backticks around schema names.
        """
        violations = []
        
        # Find all schema references (with or without backticks)
        # Pattern: word-word-word.word (schema-with-hyphens.table)
        schema_pattern = r'`?([a-z]+-[a-z]+-[a-z]+)\.([a-z_]+)`?'
        matches = re.finditer(schema_pattern, sql, re.IGNORECASE)
        
        found_unbackticked = False
        
        for match in matches:
            full_match = match.group(0)  # e.g., ems-portal-service.invoice_info or `ems-portal-service`.`invoice_info`
            schema_name = match.group(1)  # e.g., ems-portal-service
            table_name = match.group(2)   # e.g., invoice_info
            
            # Check if properly backticked
            # Correct formats:
            # `ems-portal-service`.`invoice_info`
            # `ems-portal-service`.invoice_info (table without backticks is OK)
            
            # Incorrect format:
            # ems-portal-service.invoice_info (schema has hyphens but no backticks)
            
            # Check if schema part has backticks
            schema_backticked = full_match.startswith('`') or (f'`{schema_name}`' in full_match)
            
            if not schema_backticked:
                found_unbackticked = True
                violations.append(Violation(
                    rule="SCHEMA_NAME_NOT_BACKTICKED",
                    description=f"Schema name with hyphens must be backticked: {schema_name}",
                    fix_hint=f"Use: `{schema_name}`.`{table_name}` instead of {schema_name}.{table_name}"
                ))
                break  # Only report once to avoid spam
        
        return violations
    
    def build_retry_prompt_addition(self, violations: List[Violation]) -> str:
        """
        Build additional prompt text for retry attempt.
        This provides specific feedback to the LLM about what was wrong.
        
        Args:
            violations: List of violations found
            
        Returns:
            Additional prompt text with specific corrections needed
        """
        if not violations:
            return ""
        
        retry_text = "\n\n=== CRITICAL: YOUR PREVIOUS ATTEMPT HAD ERRORS ===\n"
        retry_text += "You MUST fix these violations:\n\n"
        
        for i, v in enumerate(violations, 1):
            retry_text += f"{i}. {v.description}\n"
            retry_text += f"   FIX: {v.fix_hint}\n\n"
        
        retry_text += "Generate the corrected SQL now:\n"
        
        return retry_text
    
    def get_validation_summary(self, violations: List[Violation]) -> Dict:
        """
        Get a summary of validation results for logging.
        
        Returns:
            Dictionary with validation results
        """
        return {
            'is_valid': len(violations) == 0,
            'violation_count': len(violations),
            'violations': [
                {
                    'rule': v.rule,
                    'description': v.description
                }
                for v in violations
            ]
        }
    
    def _check_master_status_join_integrity(self, sql: str) -> List[Violation]:
        violations = []

        sql_lower = sql.lower()

        references_status_name = "master_status.name" in sql_lower
        has_join = "join" in sql_lower and "master_status" in sql_lower

        if references_status_name and not has_join:
            violations.append(Violation(
                rule="MASTER_STATUS_REFERENCE_WITHOUT_JOIN",
                description="master_status.name is referenced but master_status is not joined",
                fix_hint=(
                    "Add: JOIN `ems-portal-service`.`master_status` ms "
                    "ON ii.approval_status = ms.id"
                )
            ))

        return violations
    
    def _check_expense_category_resolution(self, sql: str, question: str) -> list[Violation]:
        violations = []
        q = question.lower()
        sql_lower = sql.lower()

        expense_keywords = [
            'rent', 'manpower', 'security', 'electricity', 'diesel',
            'transport', 'mhe', 'insurance', 'tyre', 'fuel'
        ]

        if not any(k in q for k in expense_keywords):
            return violations

        if 'expenses_master' not in sql_lower:
            violations.append(Violation(
                rule="EXPENSE_MASTER_MISSING",
                description="Expense category queries must resolve via expenses_master",
                fix_hint="Join invoice_info → invoice_line_items → expenses_master and filter on expenses_master.expense_name"
            ))

        if 'invoice_line_items' not in sql_lower:
            violations.append(Violation(
                rule="LINE_ITEMS_MISSING_FOR_EXPENSE",
                description="Expense category filtering requires invoice_line_items join",
                fix_hint="Join invoice_line_items ON invoice_line_items.invoice_id = invoice_info.id"
            ))

        return violations
    
    def _check_warehouse_source(self, sql: str) -> list[Violation]:
        violations = []
        sql_lower = sql.lower()

        if 'warehouse' in sql_lower:
            # Disallow fake warehouse tables
            if '`ems-portal-service`.`warehouse`' in sql_lower or 'warehouse ' in sql_lower:
                violations.append(Violation(
                    rule="WRONG_WAREHOUSE_TABLE",
                    description="Warehouse data must be queried from ems-warehouse-service.warehouse_info",
                    fix_hint="JOIN `ems-warehouse-service`.`warehouse_info` wi ON invoice_info.warehouse_id = wi.id"
                ))

        return violations
    

    def _check_ambiguous_columns(self, sql: str) -> list[Violation]:
        violations = []
        sql_lower = sql.lower()

        # If SUM(total_amount) is used without qualification
        if 'sum(total_amount)' in sql_lower:
            violations.append(Violation(
                rule="AMBIGUOUS_COLUMN",
                description="total_amount must be fully qualified as invoice_info.total_amount",
                fix_hint="Use SUM(invoice_info.total_amount)"
            ))

        return violations






# Convenience function
def validate_sql(sql: str, question: str) -> tuple[bool, List[Violation]]:
    """
    Convenience function for quick validation.
    
    Returns:
        (is_valid, violations) tuple
    """
    validator = SQLValidator()
    violations = validator.validate(sql, question)
    return len(violations) == 0, violations



def _build_table_schema_map(schema_json: dict) -> dict[str, str]:
    """
    Build mapping: table_name (lower) -> schema_name
    from schemas_from_mdl.json
    """
    mapping = {}
    for entity in schema_json.get("entities", {}).values():
        table = entity.get("table")
        schema = entity.get("schema")
        if table and schema:
            mapping[table.lower()] = schema
    return mapping

