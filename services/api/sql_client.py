from __future__ import annotations

import os
import json
import re
import logging
from typing import Optional, Dict, Any
from urllib.parse import quote_plus
from pathlib import Path
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine.base import Engine
from services.api.sql_refiner import refine_sql

# Import new components
from services.api.semantic_compressor import SemanticCompressor
from services.api.golden_queries import GoldenQuerySystem
from services.api.sql_validator import SQLValidator

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

logger = logging.getLogger("sql_client")
logger.setLevel(os.environ.get("SQL_CLIENT_LOG_LEVEL", "INFO"))

if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    logger.addHandler(ch)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

MAX_ROW_LIMIT = int(os.getenv("MAX_ROW_LIMIT", "1000"))
MAX_RETRY_ATTEMPTS = int(os.getenv("MAX_SQL_RETRY_ATTEMPTS", "2"))

# Regex to block dangerous write operations
_WRITE_OPS_RE = re.compile(
    r"\b(insert|update|delete|truncate|drop|alter|create|replace|merge)\b",
    re.I,
)



def extract_explicit_dates_from_question(question: str) -> tuple[str, str] | None:
    """
    Extract explicit date ranges from refined questions.
    
    Returns (start_date, end_date) as 'YYYY-MM-DD' strings, or None if not found.
    
    Examples:
    - "July 2025 to December 2025" → ('2025-07-01', '2026-01-01')
    - "from January 2025 to March 2025" → ('2025-01-01', '2025-04-01')
    - "December 2025" → ('2025-12-01', '2026-01-01')
    """
    question_lower = question.lower()
    
    # Month name to number mapping
    months = {
        'january': 1, 'jan': 1,
        'february': 2, 'feb': 2,
        'march': 3, 'mar': 3,
        'april': 4, 'apr': 4,
        'may': 5,
        'june': 6, 'jun': 6,
        'july': 7, 'jul': 7,
        'august': 8, 'aug': 8,
        'september': 9, 'sep': 9, 'sept': 9,
        'october': 10, 'oct': 10,
        'november': 11, 'nov': 11,
        'december': 12, 'dec': 12
    }
    
    # Pattern 1: "July 2025 to December 2025" or "from July 2025 to December 2025"
    pattern1 = r'(?:from\s+)?(\w+)\s+(\d{4})\s+to\s+(\w+)\s+(\d{4})'
    match = re.search(pattern1, question_lower)
    
    if match:
        start_month_str, start_year_str, end_month_str, end_year_str = match.groups()
        
        start_month = months.get(start_month_str)
        end_month = months.get(end_month_str)
        
        if start_month and end_month:
            start_date = f"{start_year_str}-{start_month:02d}-01"
            
            # End date is first day of month AFTER end_month
            end_year = int(end_year_str)
            end_month_next = end_month + 1
            if end_month_next > 12:
                end_month_next = 1
                end_year += 1
            
            end_date = f"{end_year}-{end_month_next:02d}-01"
            
            return (start_date, end_date)
    
    # Pattern 2: Single month "December 2025" or "in December 2025"
    pattern2 = r'(?:in\s+)?(\w+)\s+(\d{4})'
    match = re.search(pattern2, question_lower)
    
    if match:
        month_str, year_str = match.groups()
        month_num = months.get(month_str)
        
        if month_num:
            start_date = f"{year_str}-{month_num:02d}-01"
            
            # End date is first day of next month
            year = int(year_str)
            month_next = month_num + 1
            if month_next > 12:
                month_next = 1
                year += 1
            
            end_date = f"{year}-{month_next:02d}-01"
            
            return (start_date, end_date)
    
    return None
# ------------------------------------------------------------------
# Enhanced SQL Client
# ------------------------------------------------------------------

class SQLClient:

    TABLE_ANNOTATIONS = {
        'user': " MIXED ROLES: Contains Vendors, Admins, & Staff. MUST filter by `user_type` (e.g., 'VENDOR').",
        'invoice_info': "MONEY: Use `total_amount`.TIME: Use `invoice_month` for all monthly reporting/filtering.",     
        'invoice_line_items': "ℹDETAILS: Only use for item-level detail. NOT for total spend.",
        'quick_code_master': "LOOKUP: Use for City/Region names. NEVER for Vendor names.",
        'master_status': "STATUS: Join on `approval_status`. Filter by `name` (Approved, Pending, etc)."
    }

    def __init__(
        self,
        schema_path: Optional[str] = None,
        semantic_path: Optional[str] = None,
        db_url_override: Optional[str] = None,
    ):
        # 1. Resolve Paths
        self.schema_path = schema_path or self._find_file("schemas_from_mdl.json")
        self.semantic_path = semantic_path or self._find_file("semantic_doc.md")
        
        self.schema_json: Dict[str, Any] = {}
        self.semantic_doc: str = ""
        self.db_url_override = db_url_override
        self.engine: Optional[Engine] = None

        # 2. Load Data
        self._load_schema()
        self._load_semantics()
        
        # 3. Initialize new components
        logger.info("Initializing enhanced SQL generation system...")
        
        # Semantic compressor (reduces token usage)
        if self.semantic_path:
            self.compressor = SemanticCompressor(Path(self.semantic_path))
            logger.info("✓ Semantic compressor ready")
        else:
            self.compressor = None
            logger.warning("⚠️ Semantic compressor unavailable (no semantic doc)")
        
        # Golden query system (pattern learning)
        try:
            self.golden_system = GoldenQuerySystem()
            stats = self.golden_system.get_stats()
            logger.info(f"✓ Golden query system ready ({stats['total_examples']} examples)")
        except Exception as e:
            logger.error(f"Failed to initialize golden queries: {e}")
            self.golden_system = None
        
        # Validator (safety net)
        self.validator = SQLValidator()
        logger.info("✓ SQL validator ready")

    def _find_file(self, filename: str) -> str:
        """Helper to find config files in typical locations."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        for _ in range(4):
            candidates = [
                os.path.join(current_dir, "data", "schemas", filename),
                os.path.join(current_dir, "data", "semantic", filename),
                os.path.join(current_dir, filename)
            ]
            for path in candidates:
                if os.path.exists(path):
                    return path
            
            parent = os.path.dirname(current_dir)
            if parent == current_dir:
                break
            current_dir = parent
        return ""

    def _load_schema(self) -> None:
        if not self.schema_path or not os.path.exists(self.schema_path):
            logger.warning("⚠️ Schema file not found. LLM will hallucinate table names.")
            return
        try:
            with open(self.schema_path, "r", encoding="utf-8") as fh:
                self.schema_json = json.load(fh)
            logger.info(f"✓ Loaded schema from: {self.schema_path}")
        except Exception as e:
            logger.error(f"Failed to load schema: {e}")

    def _load_semantics(self) -> None:
        if not self.semantic_path or not os.path.exists(self.semantic_path):
            logger.warning("⚠️ Semantic doc not found. LLM will lack business logic.")
            return
        try:
            with open(self.semantic_path, "r", encoding="utf-8") as fh:
                self.semantic_doc = fh.read()
            logger.info(f"✓ Loaded semantics from: {self.semantic_path}")
        except Exception as e:
            logger.error(f"Failed to load semantics: {e}")

    # ------------------------------------------------------------------
    # Enhanced SQL Generation with RAG + Compression + Validation
    # ------------------------------------------------------------------

    def generate_sql(self, question: str, context_entities: list = None) -> str:
        """
        Generate SQL with optional follow-up context using Groq API.
        
        Args:
            question: The refined analytical question
            context_entities: List of entities from previous result (for follow-ups)
        """
        import requests
        
        # Groq API configuration
        groq_api_key = os.getenv("GROQ_API_KEY_1")
        if not groq_api_key:
            raise RuntimeError("GROQ_API_KEY_1 not set in environment variables")
        
        groq_url = "https://api.groq.com/openai/v1/chat/completions"
        model = os.getenv("GROQ_SQL_MODEL", "llama-3.1-70b-versatile")
        
        # ============================================================
        # STAGE 1: Check Golden Queries for Similar Examples
        # ============================================================
        
        if self.golden_system:
            # Find similar examples to use as learning patterns
            # We use threshold=0.60 to catch relevant patterns even if not exact
            similar_examples = self.golden_system.find_similar(question, top_k=1, threshold=0.75)
            
            if similar_examples:
                score = similar_examples[0][1]
                logger.info(f"[Golden Example Found] Will inject as pattern (similarity: {score:.3f})")
        else:
            similar_examples = []
        
        # ============================================================
        # STAGE 2: Generate with Enhanced Prompt
        # ============================================================
        
        retry_feedback = ""
        
        for attempt in range(MAX_RETRY_ATTEMPTS + 1):
            
            if attempt > 0:
                logger.info(f"[Retry {attempt}/{MAX_RETRY_ATTEMPTS}] Regenerating SQL with feedback...")
            else:
                logger.info(f"Generating SQL with model: {model}")
            
            # Build optimized prompt
            prompt = self._build_enhanced_prompt(
                question=question,
                similar_examples=similar_examples,  # Always inject if available
                retry_feedback=retry_feedback,
                context_entities=context_entities
            )
            
            # Generate SQL using Groq API
            try:
                resp = requests.post(
                    groq_url,
                    headers={
                        "Authorization": f"Bearer {groq_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.0,
                        "max_tokens": 2048
                    },
                    timeout=60
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                sql = self._clean_sql(content)
                
            except Exception as e:
                logger.error(f"Groq API Error: {e}")
                raise
            
            # ============================================================
            # STAGE 3: Validate Generated SQL
            # ============================================================
            
            violations = self.validator.validate(sql, question)
            
            if not violations:
                # Success!
                if attempt > 0:
                    logger.info(f"✓ Corrected SQL generated on retry {attempt}")
                
                # Log for potential golden promotion
                if attempt > 0 or not similar_examples:
                    self._log_successful_generation(question, sql, attempt)
                
                return sql
            
            # ============================================================
            # STAGE 4: Handle Validation Failures
            # ============================================================
            
            validation_summary = self.validator.get_validation_summary(violations)
            logger.warning(f"[Validation Failed] {validation_summary['violation_count']} violations")
            
            for v in violations:
                logger.warning(f"  - {v.rule}: {v.description}")
            
            # Last attempt failed - log and return anyway (with warning)
            if attempt >= MAX_RETRY_ATTEMPTS:
                logger.error(f"[GENERATION FAILED] Max retries reached. Returning invalid SQL.")
                self._log_failed_generation(question, sql, violations)
                return sql  # Return anyway (will likely fail at execution)
            
            # Prepare retry with specific feedback
            retry_feedback = self.validator.build_retry_prompt_addition(violations)
        
        # Should never reach here
        return sql

    def _build_enhanced_prompt(
        self,
        question: str,
        similar_examples: list,
        retry_feedback: str = "",
        context_entities: list = None
    ) -> str:
        """
        Build optimized prompt with:
        - Compressed semantics (relevant sections only)
        - Golden example if available
        - Retry feedback if this is a retry attempt
        """
        
        # 🔒 DEFENSIVE: context_entities must be a list
        if context_entities is not None and not isinstance(context_entities, list):
            logger.warning(
                "Invalid context_entities type (%s). Ignoring context.",
                type(context_entities).__name__
            )
            context_entities = None


        # Get compressed semantic doc
        if self.compressor:
            semantic_doc = self.compressor.compress(question)
            critical_rules = self.compressor.get_critical_rules_for_query(question)
        else:
            semantic_doc = self.semantic_doc
            critical_rules = []
        
        # Build prompt
        prompt_parts = []
        
        # Header
        prompt_parts.append("You are an expert SQL generator for EMS databases.")
        prompt_parts.append("")

        explicit_dates = extract_explicit_dates_from_question(question)
        if explicit_dates:
            start_date, end_date = explicit_dates
            prompt_parts.append("=" * 70)
            prompt_parts.append(" EXPLICIT DATE RANGE DETECTED ")
            prompt_parts.append("=" * 70)
            prompt_parts.append("")
            prompt_parts.append(f"The question mentions a specific date range.")
            prompt_parts.append(f"You MUST use these EXACT dates in your SQL:")
            prompt_parts.append("")
            prompt_parts.append(f"  Start: {start_date}")
            prompt_parts.append(f"  End (exclusive): {end_date}")
            prompt_parts.append("")
            prompt_parts.append("MANDATORY SQL:")
            prompt_parts.append(f"  WHERE date_column >= '{start_date}'")
            prompt_parts.append(f"  AND date_column < '{end_date}'")
            prompt_parts.append("")
            prompt_parts.append("DO NOT use DATE_SUB, CURDATE(), or INTERVAL for this query.")
            prompt_parts.append("Use the LITERAL dates shown above.")
            prompt_parts.append("")
            prompt_parts.append("=" * 70)
            prompt_parts.append("")
        
        if context_entities and len(context_entities) > 0:
            prompt_parts.append("=" * 70)
            prompt_parts.append("⚠️  FOLLOW-UP QUERY - ENTITY SCOPE RESTRICTION ⚠️")
            prompt_parts.append("=" * 70)
            prompt_parts.append("")
            prompt_parts.append(f"This query MUST filter to ONLY these {len(context_entities)} specific entities:")
            prompt_parts.append("")
            
            for i, entity in enumerate(context_entities[:15], 1):
                prompt_parts.append(f"  {i}. {entity}")
            
            if len(context_entities) > 15:
                prompt_parts.append(f"  ... and {len(context_entities) - 15} more")
            
            prompt_parts.append("")
            prompt_parts.append("MANDATORY SQL REQUIREMENT:")
            prompt_parts.append("Your WHERE clause MUST include one of:")
            prompt_parts.append("  • WHERE u.full_name IN ('entity1', 'entity2', ...)")
            prompt_parts.append("  • WHERE ai.account_name IN (...)")
            prompt_parts.append("  • WHERE wi.warehouse_name IN (...)")
            prompt_parts.append("")
            prompt_parts.append("Use LIKE for each entity: u.full_name LIKE '%entity%'")
            prompt_parts.append("Or use IN clause with exact names from list above.")
            prompt_parts.append("")
            prompt_parts.append("=" * 70)
            prompt_parts.append("")

        

        # Critical rules (highlighted)
        if critical_rules:
            prompt_parts.append("=== CRITICAL RULES (NEVER VIOLATE) ===")
            for rule in critical_rules:
                prompt_parts.append(f"- {rule}")
            prompt_parts.append("")
        
        # Similar example (if available) - BEFORE semantics for better learning
        if similar_examples:
            example, score = similar_examples[0]
            prompt_parts.append(f"=== SIMILAR EXAMPLE (Learn from this pattern, similarity: {score:.2f}) ===")
            prompt_parts.append(f"Question: {example.question}")
            prompt_parts.append(f"Correct SQL:")
            prompt_parts.append(example.sql)
            if example.notes:
                prompt_parts.append(f"Why this is correct: {example.notes}")
            prompt_parts.append("")
            prompt_parts.append("IMPORTANT: Adapt this pattern to the new question. Notice:")
            prompt_parts.append("- How status filtering is done (master_status join + LIKE)")
            prompt_parts.append("- How time calculations work (updated_at - created_at)")
            prompt_parts.append("- How geography is resolved (warehouse → quick_code_master)")
            prompt_parts.append("")
        
        # Semantic rules
        prompt_parts.append("=== SEMANTIC BUSINESS RULES ===")
        prompt_parts.append(semantic_doc)
        prompt_parts.append("")
        
        # Schema
        prompt_parts.append("=== DATABASE SCHEMA ===")
        prompt_parts.append(self._build_schema_context())
        prompt_parts.append("")
        
        now = datetime.now()
        prompt_parts.append("=== SYSTEM TIME CONTEXT ===")
        prompt_parts.append(f"Current System Date: {now.strftime('%Y-%m-%d')} ({now.strftime('%A')})")
        prompt_parts.append(f"Current Month: {now.strftime('%B %Y')}")
        prompt_parts.append("CRITICAL: All relative dates (e.g., 'last 6 months', 'this year') MUST be calculated relative to the Current System Date.")
        prompt_parts.append("")

        # Retry feedback (if this is a retry)
        if retry_feedback:
            prompt_parts.append(retry_feedback)
        
        # Task
        prompt_parts.append("=== YOUR TASK ===")
        prompt_parts.append(f"Question: {question}")
        prompt_parts.append("")
        prompt_parts.append("Instructions:")
        prompt_parts.append("1. Follow the CRITICAL RULES exactly")
        if similar_examples:
            prompt_parts.append("2. Adapt the pattern from the SIMILAR EXAMPLE above")
        prompt_parts.append("3. Generate valid MySQL compatible SQL")
        prompt_parts.append("4. Use fully qualified table names with backticks: `ems-portal-service`.`invoice_info`")
        prompt_parts.append("5. Return ONLY the SQL. No markdown, no explanations.")
        prompt_parts.append("4. Use snake_case for aliases (e.g. `vendor_name`, NOT `Vendor Name`).")
        prompt_parts.append("5. Filter by `user_type` when querying the `user` table (e.g. user_type LIKE '%VENDOR%').")
        prompt_parts.append("")
        prompt_parts.append("SQL:")
        
        return "\n".join(prompt_parts)

    def _clean_sql(self, raw: str) -> str:
        """Extracts pure SQL from LLM output, preserving CTEs."""
        # Remove markdown code blocks
        clean = re.sub(r"```(?:sql)?(.*?)```", r"\1", raw, flags=re.DOTALL)
        clean = clean.strip()
        
        # Case-insensitive search for start positions
        upper_clean = clean.upper()
        idx_with = upper_clean.find("WITH")
        idx_select = upper_clean.find("SELECT")
        
        # Logic: If 'WITH' exists and is before 'SELECT', start there.
        # Otherwise, look for 'SELECT'.
        if idx_with != -1 and (idx_select == -1 or idx_with < idx_select):
            clean = clean[idx_with:]
        elif idx_select != -1:
            clean = clean[idx_select:]
        
        # Remove trailing semi-colons and junk
        clean = clean.split(";")[0]
        
        # Enforce Limit (Be careful not to break the syntax, usually appending works)
        if "LIMIT" not in clean.upper():
            clean += f" LIMIT {MAX_ROW_LIMIT}"
            
        return clean

    def _build_schema_context(self) -> str:
        """
        Convert JSON schema to string.
        FIX: Prioritize CORE tables so they are never truncated.
        """
        if not self.schema_json:
            return ""
        
        # 1. Define Priority Tables (Must match your Critical Rules)
        PRIORITY_TABLES = {
            'invoice_info', 
            'invoice_line_items', 
            'user',              # Critical for Vendor
            'master_status',     # Critical for Status
            'quick_code_master', # Critical for Lookups
            'warehouse_info',
            'account_info'
        }
        
        entities = self.schema_json.get("entities", {})
        out = []
        
        # 2. Add Priority Tables First
        for name, info in entities.items():
            if info.get('table') in PRIORITY_TABLES:
                out.append(self._format_table_schema(info))
        
        # 3. Add other tables until limit (e.g., 15 total)
        count = len(out)
        for name, info in entities.items():
            if info.get('table') not in PRIORITY_TABLES:
                if count >= 15: break
                out.append(self._format_table_schema(info))
                count += 1
                
        return "\n".join(out)

    def _format_table_schema(self, info: dict) -> str:
        table_name = info.get('table')
        lines = [f"Table: {info.get('schema')}.{table_name}"]
        
        # [START CHANGED BLOCK]
        # 1. Inject Annotation if available
        if table_name in self.TABLE_ANNOTATIONS:
            lines.append(f"  NOTE: {self.TABLE_ANNOTATIONS[table_name]}")
        # [END CHANGED BLOCK]
            
        # 2. List columns
        for col in info.get("columns", [])[:10]:
            lines.append(f" - {col.get('name')} ({col.get('type')})")
        
        lines.append("")
        return "\n".join(lines)
    
    def _log_successful_generation(self, question: str, sql: str, attempts: int):
        """Log successful SQL generation (for analysis/golden promotion)."""
        if attempts > 0:
            logger.info(f"[Success After Retry] Consider promoting to golden query")
            # Future: Auto-promote queries that needed retry
    
    def _log_failed_generation(self, question: str, sql: str, violations: list):
        """Log failed generation for manual review/golden promotion."""
        logger.error(f"[FAILED GENERATION]")
        logger.error(f"Question: {question}")
        logger.error(f"Generated SQL: {sql}")
        logger.error(f"Violations: {[v.rule for v in violations]}")
        logger.error("→ RECOMMENDATION: Manually correct and add as golden query")
        
        # Future: Write to file for batch review
        # failed_log = Path("data/failed_queries.jsonl")
        # failed_log.parent.mkdir(parents=True, exist_ok=True)
        # with open(failed_log, 'a') as f:
        #     json.dump({
        #         'question': question,
        #         'sql': sql,
        #         'violations': [v.rule for v in violations]
        #     }, f)
        #     f.write('\n')

    # ------------------------------------------------------------------
    # Execution (Database)
    # ------------------------------------------------------------------

    def execute_sql(self, sql: str) -> pd.DataFrame:
        # Refine SQL (semantic fixes)
        sql = refine_sql(sql)

        # Validate
        self.validate_sql(sql)

        # 🔒 EXECUTION-SAFETY: escape % for SQLAlchemy / PyMySQL
        sql = sql.replace('%', '%%')

        # Get Engine
        engine = self._get_engine()

        # Run
        logger.info("Executing SQL...")
        return pd.read_sql(sql, con=engine)

    def validate_sql(self, sql: str):
        upper_sql = sql.strip().upper()
        
        # FIX: Allow 'WITH' for CTEs alongside 'SELECT'
        if not (upper_sql.startswith("SELECT") or upper_sql.startswith("WITH")):
            raise ValueError("Only SELECT or WITH (CTE) queries allowed.")
            
        if _WRITE_OPS_RE.search(sql):
            raise ValueError("Write operations forbidden.")

    def _get_engine(self) -> Engine:
        if self.engine:
            return self.engine

        # 1. Check override first
        url = self.db_url_override
        
        # 2. Build from Env if no override
        if not url:
            host = os.getenv("LIVE_DB_HOST", "localhost")
            user = os.getenv("LIVE_DB_USER")
            pwd = os.getenv("LIVE_DB_PASSWORD", "")
            db = os.getenv("LIVE_DB_NAME")
            port = os.getenv("LIVE_DB_PORT", "3306")

            if not (user and db):
                raise ValueError("Missing DB credentials (LIVE_DB_USER or LIVE_DB_NAME)")

            url = f"mysql+pymysql://{user}:{quote_plus(pwd)}@{host}:{port}/{db}"

        logger.info(f"Connecting to DB: {os.getenv('LIVE_DB_HOST')}/{os.getenv('LIVE_DB_NAME')}")
        
        try:
            self.engine = create_engine(url, pool_pre_ping=True)
            return self.engine
        except Exception as e:
            logger.error(f"Engine creation failed: {e}")
            raise
    
    # ------------------------------------------------------------------
    # Golden Query Management (API for frontend/CLI)
    # ------------------------------------------------------------------
    
    def add_golden_query(self, question: str, sql: str, notes: str = "", tags: list = None):
        """Add a corrected query to golden examples."""
        if not self.golden_system:
            logger.error("Golden query system not available")
            return False
        
        self.golden_system.add_example(question, sql, notes, tags)
        logger.info(f"✓ Added golden query. System will learn from this pattern.")
        return True
    
    def get_golden_stats(self) -> dict:
        """Get statistics about golden query system."""
        if not self.golden_system:
            return {'available': False}
        
        return self.golden_system.get_stats()