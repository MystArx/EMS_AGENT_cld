import os
import json
import logging
import requests
import re
from pathlib import Path
from typing import Dict, Any
from typing import Optional

from services.api.chat_state import ChatState

from services.api.refiner_semantic_compressor import RefinerSemanticCompressor

logger = logging.getLogger("groq_refiner")

# -------------------------------------------------------------------
# Groq configuration
# -------------------------------------------------------------------

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY not set")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv(
    "GROQ_REFINER_MODEL",
    "llama-3.1-8b-instant",
)

# -------------------------------------------------------------------
# Refiner semantics with compression
# -------------------------------------------------------------------

REFINER_SEMANTICS_PATH = Path("data/semantic/business_semantic.md")

if not REFINER_SEMANTICS_PATH.exists():
    raise RuntimeError(
        f"Refiner semantics file not found: {REFINER_SEMANTICS_PATH}"
    )

# Initialize refiner compressor
try:
    refiner_compressor = RefinerSemanticCompressor(REFINER_SEMANTICS_PATH)
    logger.info("✓ Refiner semantic compressor initialized")
except Exception as e:
    logger.warning(f"Could not initialize refiner compressor: {e}")
    refiner_compressor = None
    # Fallback: load full doc
    REFINER_SEMANTICS_FULL = REFINER_SEMANTICS_PATH.read_text()

# -------------------------------------------------------------------
# JSON extraction (DEFENSIVE)
# -------------------------------------------------------------------

_JSON_OBJECT_RE = re.compile(
    r"\{[\s\S]*\}",
    re.MULTILINE,
)


def _safe_parse_json(text: str) -> Dict[str, Any]:
    """
    Strict JSON parse first.
    Fallback: extract the first JSON object from mixed text.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = _JSON_OBJECT_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError("No valid JSON object found in LLM response")

# -------------------------------------------------------------------
# Semantic compression for refiner
# -------------------------------------------------------------------

def _compress_refiner_semantics(user_input: str) -> str:
    """
    Compress refiner semantics based on query keywords.
    Uses the dedicated RefinerSemanticCompressor.
    """
    if refiner_compressor:
        return refiner_compressor.compress(user_input)
    else:
        # Fallback: return full doc if compressor not available
        return REFINER_SEMANTICS_FULL
#--------------------------------------------------------------------

def _detect_followup_mode(user_input: str, state: ChatState) -> bool:
    """
    Detect if this is a follow-up question referring to previous results.
    """
    # No previous results = can't be follow-up
    if not state.last_result_entities or state.last_result_count == 0:
        return False
    
    user_lower = user_input.lower()
    
    # Strong follow-up indicators
    followup_keywords = [
        "which one", "which vendor", "which account", "which warehouse",
        "from those", "from these", "from that list", "from the list",
        "among them", "among these", "out of those",
        "that", "those", "these", "them", "they",
        "the one", "the vendor", "the account",
        "same", "also", "in which months", "which months",
        "when did", "missing months"
    ]
    
    # Check for follow-up keywords
    has_followup_keyword = any(kw in user_lower for kw in followup_keywords)
    
    # Check for pronouns without entity names
    has_pronoun = any(word in user_lower for word in ["which", "that", "those", "these", "them", "they"])
    has_entity_name = any(
        entity.lower() in user_lower 
        for entity in state.last_result_entities[:5]
    )
    
    is_followup = has_followup_keyword or (has_pronoun and not has_entity_name)
    
    if is_followup:
        logger.info(f"🔗 FOLLOW-UP DETECTED: User referring to previous {state.last_result_count} results")
    
    return is_followup

def _needs_ranking_clarification(user_input: str, state: ChatState) -> Optional[str]:
    """
    Decide if we MUST ask a clarification question instead of refining.
    Returns clarification question string or None.
    """

    # No previous list → no ambiguity
    if not state.last_result_entities or state.last_result_count <= 1:
        return None

    user_lower = user_input.lower()

    ranking_words = [
        "most", "least", "highest", "lowest",
        "best", "worst", "top", "bottom"
    ]

    if not any(w in user_lower for w in ranking_words):
        return None

    # User explicitly scoped it → no clarification
    explicit_scope = [
        "among", "within", "from these", "from those",
        "overall", "globally", "across all"
    ]

    if any(p in user_lower for p in explicit_scope):
        return None

    # Ambiguous ranking → MUST clarify
    entity_type = (
        "vendors" if "vendor" in (state.last_query_type or "")
        else "accounts" if "account" in (state.last_query_type or "")
        else "warehouses"
    )

    return (
        f"Do you mean among the previously listed {entity_type}, "
        f"or across all {entity_type}?"
    )

def _needs_location_disambiguation(user_input: str) -> bool:
    user_lower = user_input.lower()

    # Matches patterns like "trichy 1", "chennai 2", etc.
    has_city_number_pattern = bool(
        re.search(r'\b[a-z]+\\s+\\d+\\b', user_lower)
    )

    # City names are valid entities
    known_city = any(
        city.lower() in user_lower
        for city in ["trichy", "chennai", "bangalore", "mumbai"]
    )

    return has_city_number_pattern and known_city


def _build_followup_constraint(state: ChatState) -> str:
    """
    Build explicit constraint for follow-up questions.
    """
    if not state.last_result_entities:
        return ""
    
    # Determine entity type from query type
    entity_col = None
    if "vendor" in state.last_query_type:
        entity_col = "vendor_name"
    elif "account" in state.last_query_type:
        entity_col = "account_name"
    elif "warehouse" in state.last_query_type:
        entity_col = "warehouse_name"
    
    if not entity_col:
        return ""
    
    # Format entity list (max 15)
    entities = state.last_result_entities[:15]
    entity_list = ", ".join(f"'{e}'" for e in entities)
    
    constraint = f"""
🔗 CRITICAL FOLLOW-UP CONSTRAINT 🔗
The user is asking about entities from the PREVIOUS query result.
You MUST explicitly mention these {len(entities)} specific entities in your refined question:
{', '.join(entities[:10])}{'...' if len(entities) > 10 else ''}

Your refined question MUST include: "... for vendors [list names] ..." or similar explicit reference.
DO NOT make this a global query. Scope MUST remain limited to these entities.
"""
    
    return constraint


def _parse_calendar_time(user_input: str) -> dict:
    """
    Parse time expressions into calendar-based SQL.
    Returns dict with 'description' and 'sql_filter'.
    """
    from datetime import datetime, timedelta
    import calendar
    
    user_lower = user_input.lower()
    today = datetime.now()
    
    # Last month = previous complete calendar month
    if "last month" in user_lower:
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)
        
        return {
            "description": f"last month ({first_day_last_month.strftime('%B %Y')})",
            "sql_filter": f"date_column >= '{first_day_last_month.strftime('%Y-%m-%d')}' AND date_column < '{first_day_this_month.strftime('%Y-%m-%d')}'"
        }
    
    # Last N months = previous N complete calendar months
    import re
    last_n_match = re.search(r'last (\d+) months?', user_lower)
    if last_n_match:
        n = int(last_n_match.group(1))
        first_day_this_month = today.replace(day=1)
        
        # Go back N months
        target_month = today.month - n
        target_year = today.year
        while target_month < 1:
            target_month += 12
            target_year -= 1
        
        first_day = datetime(target_year, target_month, 1)
        
        return {
            "description": f"last {n} months ({first_day.strftime('%B %Y')} to {(first_day_this_month - timedelta(days=1)).strftime('%B %Y')})",
            "sql_filter": f"date_column >= '{first_day.strftime('%Y-%m-%d')}' AND date_column < '{first_day_this_month.strftime('%Y-%m-%d')}'"
        }
    
    # This month = current calendar month
    if "this month" in user_lower or "current month" in user_lower:
        first_day = today.replace(day=1)
        return {
            "description": f"this month ({today.strftime('%B %Y')})",
            "sql_filter": f"date_column >= '{first_day.strftime('%Y-%m-%d')}' AND date_column <= '{today.strftime('%Y-%m-%d')}'"
        }
    
    return None

# -------------------------------------------------------------------
# Prompt builder (HARDENED + COMPRESSION + CONTEXT)
# -------------------------------------------------------------------

def _build_prompt(user_input: str, state: ChatState, is_followup_mode: bool = True) -> str:
    """Build refiner prompt with follow-up awareness and calendar time parsing"""
    
    # 1. Build Recent Chat History
    recent = "\n".join(
        f"{t['role'].upper()}: {t['content']}"
        for t in state.recent_turns[-2:]
    )
    
    # 2. Get Compressed Semantics
    compressed_semantics = _compress_refiner_semantics(user_input)
    
    # 3. Detect Follow-up Mode
    is_followup = _detect_followup_mode(user_input, state)
    
    # 4. Build Follow-up Constraint
    followup_constraint = ""
    if is_followup:
        followup_constraint = _build_followup_constraint(state)
    
    # 5. Parse Calendar Time Expressions
    time_parse = _parse_calendar_time(user_input)
    time_hint = ""
    if time_parse:
        time_hint = f"""
📅 TIME INTERPRETATION:
User said: "{user_input}"
This means: {time_parse['description']}
Include this in your refined question to make the time period clear.
"""
    
    # 6. Build Result Context (Previous query results)
    result_context = ""
    if state.last_result_entities:
        entities_str = ', '.join(state.last_result_entities[:10])
        if len(state.last_result_entities) > 10:
            entities_str += "..."
            
        result_context = f"""
PREVIOUS QUERY RESULT:
- Question: {state.last_refined_question}
- Returned: {state.last_result_count} {state.last_query_type}
- Entities: {entities_str}
"""

    # 7. SUBSTITUTION HEURISTIC (The Fix for "in Dasna 2?")
    # Heuristic: Short input + Previous valid question = Likely Substitution
    is_short_input = len(user_input.split()) < 7
    substitution_hint = ""
    
    if is_short_input and state.last_refined_question:
        substitution_hint = (
            f"SUBSTITUTION DETECTED: The user input is short ('{user_input}'). "
            "They are likely asking to run the PREVIOUS question with a NEW entity. "
            f"Previous Question: '{state.last_refined_question}'. "
            "Task: Replace the entity in the previous question with the new one from user input."
        )

    # 8. Safe JSON formatting for State
    current_state_json = f"""{{
  "last_account": {json.dumps(state.last_account)},
  "last_vendor": {json.dumps(state.last_vendor)},
  "last_warehouse": {json.dumps(state.last_warehouse)},
  "last_city": {json.dumps(state.last_city)},
  "last_region": {json.dumps(state.last_region)},
  "last_metric": {json.dumps(state.last_metric)},
  "last_time_filter": {json.dumps(state.last_time_filter)}
}}"""

    context_entities_json = json.dumps(state.last_result_entities[:10]) if is_followup else "null"

    # 9. Construct Final Prompt
    prompt = f"""
You are an analytics query refiner for an Expense Management System (EMS).

You understand business meaning but NOT databases or SQL.

RULES:
1. ENTITY SWAPPING: If the user input is just an entity name (e.g., "in Dasna 2"), preserve the intent and swap the entity.
   - Bad: "Where is Dasna 2?"
   - Good: "What is the total expense in Dasna 2...?"

2. TIME PARSING: Use the "TIME INTERPRETATION" block below to interpret relative dates.

3. FOLLOW-UP CONTEXT: If the user asks about "they" or "those", explicitly list the entities from the PREVIOUS RESULT in the new question.

4. RESTRUCTURING & PIVOTS: If the user asks to "group by X" or "list by X", do NOT append the text literally. Rewrite the question to make 'X' the primary subject.
   - Previous: "Which warehouses do they operate in?" (Result: Warehouse -> Vendor List)
   - User: "group by vendor"
   - Bad: "Which warehouses do they operate in group by vendor?"
   - Good: "List the warehouses associated with each of the top 5 vendors." (Pivots the view)

IMPORTANT:
- Your ENTIRE response MUST be valid JSON
- Do NOT include explanations
- Do NOT repeat the user query unless refining it

--- REFINER SEMANTICS (COMPRESSED) ---
{compressed_semantics}
---------------------------------------------------------------

RECENT CONTEXT:
{recent if recent else "None"}

{result_context}

{followup_constraint}

{time_hint}

{substitution_hint}

{"⚠️ FOLLOW-UP MODE ACTIVE ⚠️" if is_followup else ""}
{"The user is asking about entities from the PREVIOUS result." if is_followup else ""}
{"You MUST explicitly mention those specific entities in your refined question." if is_followup else ""}

CURRENT STATE:
{current_state_json}

USER QUERY:
"{user_input}"

OUTPUT FORMAT (JSON ONLY):
{{
  "refined_question": null | string,
  "state_updates": {{
    "last_account": null | string,
    "last_vendor": null | string,
    "last_warehouse": null | string,
    "last_city": null | string,
    "last_region": null | string,
    "last_metric": null | string,
    "last_time_filter": null | string
  }},
  "needs_clarification": boolean,
  "clarification_question": null | string,
  "is_followup": {str(is_followup).lower()},
  "context_entities": {context_entities_json}
}}

CRITICAL EXAMPLES FOR FOLLOW-UP:

Example 1 - Vendor Follow-up:
Previous: "15 vendors inconsistent: KBR Enterprises, Safe X Security, ..."
User: "in which months were they inconsistent?"
Correct: "In which months did vendors KBR Enterprises, Safe X Security, [and 13 others] fail to upload invoices?"
Wrong: "In which months were vendors inconsistent?" (too vague)

Example 2 - Temporal Follow-up:
Previous: "Vendors who haven't uploaded in last 6 months"
User: "which months for KBR?"
Correct: "Which specific months in the last 6 months is vendor KBR Enterprises missing invoice uploads?"
Wrong: "Show KBR Enterprises data" (lost temporal context)
""".strip()
    
    return prompt

# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def refine_with_groq(
    user_input: str,
    state: ChatState,
) -> Dict[str, Any]:
    """
    Groq-based refiner with compression and result context.

    HARD CONTRACT:
    - Never crashes on malformed output
    - Never raises for missing refined_question
    - ChatController owns fallback & clarification logic
    """

    clarification = _needs_ranking_clarification(user_input, state)
    if clarification:
        logger.info("🟡 Clarification required (pre-LLM)")
        return {
            "needs_clarification": True,
            "clarification_question": clarification,
            "refined_question": None,
            "state_updates": {},
            "is_followup": True,
            "context_entities": state.last_result_entities,
        }
    if _needs_location_disambiguation(user_input):
        return {
            "needs_clarification": True,
            "clarification_question":
                "Do you mean vendors operating in the specific warehouse named "
                "'Trichy 1', or vendors operating in warehouses located in the city Trichy?",
            "refined_question": None,
            "state_updates": {},
            "is_followup": True,
            "context_entities": None
        }


    prompt = _build_prompt(user_input, state)
    logger.info("Calling Groq refiner (with compression + context)")

    try:
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "temperature": 0,
                "max_tokens": 512,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
            },
            timeout=8,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error("Groq request failed: %s", e)
        raise  # transport failure is real failure

    content = resp.json()["choices"][0]["message"]["content"].strip()

    # Remove common wrappers
    if content.startswith("```"):
        content = content.strip("```").replace("json", "").strip()

    try:
        data = _safe_parse_json(content)
        ctx = data.get("context_entities")

        if isinstance(ctx, dict):
            # flatten known keys
            for key in ("accounts", "vendors", "warehouses"):
                if key in ctx and isinstance(ctx[key], list):
                    data["context_entities"] = ctx[key]
                    break
            else:
                data["context_entities"] = None

    except Exception:
        logger.error("Groq returned unparsable output:\n%s", content)
        # SAFE FALLBACK
        return {
            "needs_clarification": False,
            "clarification_question": None,
            "refined_question": user_input,
            "state_updates": {},
        }

    # ----------------------------
    # Clarification path
    # ----------------------------
    if data.get("needs_clarification"):
        return {
            "needs_clarification": True,
            "clarification_question": data.get("clarification_question"),
            "refined_question": None,
            "state_updates": data.get("state_updates", {}),
            "is_followup": data.get("is_followup", False),
            "context_entities": data.get("context_entities")
        }

    # Analytics path
    return {
        "needs_clarification": False,
        "clarification_question": None,
        "refined_question": data.get("refined_question"),
        "state_updates": data.get("state_updates", {}),
        "is_followup": data.get("is_followup", False),
        "context_entities": data.get("context_entities")
    }