from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass
class ChatState:
    session_id: str

    # short rolling history (language continuity)
    recent_turns: List[Dict[str, str]] = field(default_factory=list)

    # authoritative extracted state
    last_account: Optional[str] = None
    last_vendor: Optional[str] = None
    last_warehouse: Optional[str] = None
    last_city: Optional[str] = None
    last_region: Optional[str] = None
    last_metric: Optional[str] = None
    last_time_filter: Optional[str] = None
    pending_clarification_question: Optional[str] = None
    pending_user_query: Optional[str] = None
    last_refined_question: Optional[str] = None  # The analytical question asked
    last_query_type: Optional[str] = None  # "vendor_list", "invoice_count", "account_ranking", etc.
    last_result_entities: List[str] = field(default_factory=list)  # Entity names returned (e.g., vendor names)
    last_result_count: int = 0  # Number of results returned
    last_sql_query: Optional[str] = None  # The SQL that was executed

    def add_turn(self, role: str, content: str, max_turns: int = 4):
        self.recent_turns.append({"role": role, "content": content})
        if len(self.recent_turns) > max_turns:
            self.recent_turns.pop(0)
    
    def update_result_context(
        self,
        refined_question: str,
        query_type: str,
        result_entities: List[str],
        result_count: int,
        sql_query: str
    ):
        """
        Update context after a query is executed.
        This allows follow-up questions to reference previous results.
        
        Args:
            refined_question: The analytical question that was asked
            query_type: Type of query (vendor_list, account_ranking, etc.)
            result_entities: List of entity names from results (e.g., vendor names)
            result_count: Total number of results returned
            sql_query: The SQL that was executed
        """
        self.last_refined_question = refined_question
        self.last_query_type = query_type
        self.last_result_entities = result_entities
        self.last_result_count = result_count
        self.last_sql_query = sql_query
    
    def get_result_context_summary(self) -> str:
        """
        Generate a human-readable summary of the last query results.
        Used to inject context into the refiner.
        
        Returns:
            String summary like "15 vendors: KBR Enterprises, Safe X Security, ..."
        """
        if not self.last_result_entities:
            return "No previous query results"
        
        entity_preview = ", ".join(self.last_result_entities[:5])
        if len(self.last_result_entities) > 5:
            entity_preview += f", ... (and {len(self.last_result_entities) - 5} more)"
        
        return f"{self.last_result_count} {self.last_query_type or 'results'}: {entity_preview}"
    
    def clear_result_context(self):
        """Clear result context (e.g., on session reset)"""
        self.last_refined_question = None
        self.last_query_type = None
        self.last_result_entities = []
        self.last_result_count = 0
        self.last_sql_query = None

    def reset_analytical_context(self):
        """
        Hard reset for 'New Question Mode'.
        Clears ALL analytical carry-over but keeps session alive.
        """
        self.last_account = None
        self.last_vendor = None
        self.last_warehouse = None
        self.last_city = None
        self.last_region = None
        self.last_metric = None
        self.last_time_filter = None
        self.last_refined_question = None
        self.last_query_type = None
        self.last_result_entities = []
        self.last_result_count = 0
        self.last_sql_query = None
