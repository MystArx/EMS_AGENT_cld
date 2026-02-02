from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class ChatRequest(BaseModel):
    message: str
    session_id: str
    use_followup_context: bool = True

class ChatResponse(BaseModel):
    type: str  # "GREETING", "CLARIFICATION", "ANALYTICS"
    message: Optional[str] = None
    refined_question: Optional[str] = None
    # We send state updates to frontend so it can visualize them if needed
    current_state: Optional[Dict[str, Any]] = None

class GenerateSQLRequest(BaseModel):
    refined_question: str
    session_id: str
    use_followup_context: bool = False 

class SQLProposalResponse(BaseModel):
    sql: str
    explanation: str = "Generated based on schema and semantics."

class ExecuteSQLRequest(BaseModel):
    sql: str
    refined_question: Optional[str] = ""  
    session_id: Optional[str] = ""
    


class ExecuteSQLResponse(BaseModel):
    columns: List[str]
    data: List[Dict[str, Any]]
    row_count: int
    execution_time: float
    error: str | None = None


class AddGoldenQueryRequest(BaseModel):
    question: str
    sql: str
    notes: str = ""
    tags: list = []

class AdminCorrectionRequest(BaseModel):
    refined_question: str
    incorrect_sql: str
    corrected_sql: str
    correction_notes: str = ""

class AdminCorrectionResponse(BaseModel):
    success: bool
    message: str
    golden_query_added: bool
    total_golden_queries: int


class FeedbackRequest(BaseModel):
    timestamp: str
    session_id: str
    feedback_type: str  # "correct" or "wrong"
    user_question: str
    refined_question: str
    generated_sql: str
    result_count: int
    chat_state: dict
    user_role: str = "user"  # "user" or "admin"