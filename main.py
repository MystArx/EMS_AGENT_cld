from dotenv import load_dotenv
load_dotenv()

import asyncio
import time
from fastapi import FastAPI, HTTPException, Body
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel
from api_models import AdminCorrectionRequest, AdminCorrectionResponse, FeedbackRequest
import logging
from datetime import datetime
from pathlib import Path
import json
logger = logging.getLogger(__name__)


from api_models import (
    ChatRequest, ChatResponse, 
    GenerateSQLRequest, SQLProposalResponse, 
    ExecuteSQLRequest, ExecuteSQLResponse, AddGoldenQueryRequest
)
from dependencies import get_chat_controller, get_sql_client

# --- GLOBAL STATE ---
SYSTEM_STATUS = {
    "ready": False,
    "message": "Initializing..."
}

# --- STARTUP LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Start Warm-up in Background
    asyncio.create_task(warmup_system())
    yield
    # Cleanup (if needed)

async def warmup_system():
    """Runs heavy model loading without blocking the server startup"""
    global SYSTEM_STATUS
    print(">>> SYSTEM: Beginning Background Warm-up...")
    SYSTEM_STATUS["message"] = "Warming up AI Models..."
    
    try:
        client = get_sql_client() # Loads Schema/Semantics
        # Force model load
        await run_in_threadpool(client.generate_sql, "select 1")
        
        SYSTEM_STATUS["ready"] = True
        SYSTEM_STATUS["message"] = "Online"
        print(">>> SYSTEM: Warm-up Complete. API Ready.")
    except Exception as e:
        SYSTEM_STATUS["message"] = f"Startup Failed: {str(e)}"
        print(f">>> SYSTEM ERROR: {e}")

app = FastAPI(title="EMS Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def log_sql_execution_error(
    *,
    session_id: str | None,
    refined_question: str | None,
    sql: str,
    exc: Exception,
):
    log_dir = Path("data/sql_error_logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    error_file = log_dir / "sql_execution_errors.jsonl"

    with open(error_file, "a") as f:
        json.dump(
            {
                "session_id": session_id,
                "refined_question": refined_question,
                "sql": sql,
                "error": str(exc),
                "timestamp": datetime.now().isoformat(),
            },
            f,
        )
        f.write("\n")


# --- DEPENDENCY CHECK ---
def check_readiness():
    if not SYSTEM_STATUS["ready"]:
        raise HTTPException(status_code=503, detail=f"System is warming up: {SYSTEM_STATUS['message']}")

# --- ENDPOINTS ---

@app.get("/api/status")
def get_status():
    """Frontend polls this to know when to remove the loading screen"""
    return SYSTEM_STATUS

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    check_readiness()
    controller = get_chat_controller(request.session_id)
    #HARD RESET FOR NEW QUESTION MODE
    if getattr(request, "use_followup_context", True) is False:
        controller.state.reset_analytical_context()

    result = await run_in_threadpool(controller.handle_message, request.message)
    
    current_state = {
        "last_metric": controller.state.last_metric,
        "last_vendor": controller.state.last_vendor,
        "pending_clarification": controller.state.pending_clarification_question
    }

    return ChatResponse(
        type=result["type"],
        message=result.get("message"),
        refined_question=result.get("refined_question"),
        current_state=current_state
    )

@app.post("/api/generate-sql", response_model=SQLProposalResponse)
async def generate_sql_endpoint(request: GenerateSQLRequest):
    check_readiness()
    client = get_sql_client()
    controller = get_chat_controller(request.session_id)
    context_entities = None
    
    # NEW: Only use context if explicitly requested via follow-up mode
    if request.use_followup_context:
        question_lower = request.refined_question.lower()
        
        followup_indicators = [
            "they", "them", "those", "these",
            "which months", "in which", "for them",
            "among them", "from those", "the one", "which one",
            "missing months", "when did"
        ]
        
        has_followup = any(indicator in question_lower for indicator in followup_indicators)
        
        # Only pass context if both conditions are met:
        # 1. User explicitly enabled follow-up mode
        # 2. Question has follow-up indicators OR context exists
        if request.use_followup_context:
            if controller.state.last_result_entities:
                context_entities = controller.state.last_result_entities
            else:
                context_entities = None

            if isinstance(context_entities, list):
                logger.info(f"🔗 Follow-up mode ENABLED: Passing {len(context_entities)} context entities")
                logger.info(f"   Entities: {context_entities[:3]}...")
            elif isinstance(context_entities, dict):
                logger.info(
                    "🔗 Follow-up mode ENABLED: Passing projection-only follow-up context "
                    f"(query_type={context_entities.get('query_type')})"
                )
            else:
                logger.info("🔗 Follow-up mode ENABLED: Context present (unknown structure)")

    else:
        logger.info(f"🆕 Independent question mode: No context passed")
    try:
        print(f"\n>>> GENERATING SQL FOR: {request.refined_question}")
        print(f">>> Follow-up mode: {request.use_followup_context}")
        
        # Pass context to generator only if follow-up mode is enabled
        sql = await run_in_threadpool(
            client.generate_sql,
            request.refined_question,
            context_entities=context_entities
        )

        print(f">>> GENERATED SQL:\n{sql}\n")
        return SQLProposalResponse(sql=sql)
    except Exception as e:
            print(f"ERROR GENERATING SQL: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/execute-sql", response_model=ExecuteSQLResponse)
async def execute_sql_endpoint(request: ExecuteSQLRequest):
    check_readiness()
    client = get_sql_client()
    
    # Extra safety for 'Admin' bypasses
    clean_sql = request.sql.strip().upper()
    if not (clean_sql.startswith("SELECT") or clean_sql.startswith("WITH")):
        raise HTTPException(status_code=400, detail="Only SELECT or WITH queries allowed.")

    try:
        t0 = time.time()
        df = await run_in_threadpool(client.execute_sql, request.sql)
        
        # NEW: Update query results for context (if session provided)
        if request.session_id and request.refined_question:
            try:
                controller = get_chat_controller(request.session_id)
                controller.update_query_results(
                    refined_question=request.refined_question,
                    sql=request.sql,
                    result_df=df
                )
            except Exception as e:
                # Don't fail the whole request if context update fails
                logger.warning(f"Failed to update query context: {e}")
        
        return ExecuteSQLResponse(
            columns=list(df.columns),
            data=df.to_dict(orient="records"),
            row_count=len(df),
            execution_time=time.time() - t0
        )
    except Exception as e:
        # Log SQL execution failure
        log_sql_execution_error(
            session_id=request.session_id,
            refined_question=request.refined_question,
            sql=request.sql,
            exc=e,
        )

        logger.exception("SQL execution failed")

        # IMPORTANT: return 200 so frontend can recover
        return ExecuteSQLResponse(
            columns=[],
            data=[],
            row_count=0,
            execution_time=time.time() - t0,
            error="SQL execution failed. You can ask a new question or rephrase."
        )


    
#---Golden Query---

@app.post("/api/golden-query/add")
async def add_golden_query(request: AddGoldenQueryRequest):
    """
    Allow users to save corrected queries.
    Frontend calls this after user manually fixes bad SQL.
    """
    check_readiness()
    client = get_sql_client()
    
    success = client.add_golden_query(
        question=request.question,
        sql=request.sql,
        notes=request.notes,
        tags=request.tags
    )
    
    return {"success": success, "message": "Query saved. System will learn from this pattern."}

@app.get("/api/golden-query/stats")
async def get_golden_stats():
    """Get statistics about the learning system."""
    check_readiness()
    client = get_sql_client()
    return client.get_golden_stats()


@app.post("/api/admin/correct-sql", response_model=AdminCorrectionResponse)
async def admin_correct_sql(request: AdminCorrectionRequest):
    """
    Admin endpoint to submit SQL corrections.
    Automatically adds corrected query to golden examples.
    """
    check_readiness()
    client = get_sql_client()
    
    try:
        # Add to golden queries
        success = client.add_golden_query(
            question=request.refined_question,
            sql=request.corrected_sql,
            notes=request.correction_notes or "Admin correction",
            tags=["admin_correction"]
        )
        
        if success:
            stats = client.get_golden_stats()
            return AdminCorrectionResponse(
                success=True,
                message="SQL correction saved. System will learn from this pattern.",
                golden_query_added=True,
                total_golden_queries=stats.get('total_examples', 0)
            )
        else:
            return AdminCorrectionResponse(
                success=False,
                message="Failed to save correction",
                golden_query_added=False,
                total_golden_queries=0
            )
            
    except Exception as e:
        logger.error(f"Error saving admin correction: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/api/feedback")
async def submit_feedback(request: FeedbackRequest):
    """
    Log user feedback on query results.
    Business users: feedback logged only
    Admin users: can also correct and teach system
    """
    try:
        # Create feedback log directory
        log_dir = Path("data/feedback_logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Log to daily file
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"feedback_{today}.jsonl"
        
        with open(log_file, 'a') as f:
            json.dump(request.dict(), f)
            f.write('\n')
        
        logger.info(f"📝 Feedback: {request.feedback_type} from {request.user_role} - {request.refined_question[:50]}")
        
        # If marked wrong, add to priority review
        if request.feedback_type == "wrong":
            priority_file = log_dir / "priority_review.jsonl"
            with open(priority_file, 'a') as f:
                json.dump({
                    **request.dict(),
                    "priority": "high",
                    "logged_at": datetime.now().isoformat()
                }, f)
                f.write('\n')
            
            logger.warning(f"⚠️  Priority review: Wrong result flagged for: {request.refined_question}")
        
        return {
            "success": True,
            "message": "Feedback recorded. Thank you!",
            "log_file": str(log_file)
        }
        
    except Exception as e:
        logger.error(f"Failed to log feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))