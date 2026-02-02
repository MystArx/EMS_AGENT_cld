from services.api.chat_state import ChatState
from services.api.groq_refiner import refine_with_groq
import pandas as pd
from typing import Optional


class ChatController:
    def __init__(self, session_id: str):
        self.state = ChatState(session_id=session_id)

    def handle_message(self, text: str) -> dict:
        """
        Main chat entrypoint.

        Returns one of:
        - GREETING
        - CLARIFICATION
        - ANALYTICS
        """

        # -------------------------------------------------
        # Clarification answer handling (MUST BE FIRST)
        # -------------------------------------------------
        clarification_in_progress = (
            self.state.pending_clarification_question is not None
        )

        if clarification_in_progress:
            combined_input = (
                f"Original question: {self.state.pending_user_query}\n"
                f"Clarification answer: {text}"
            )

            # 🔴 CRITICAL: close clarification BEFORE refinement
            self.state.pending_clarification_question = None
            self.state.pending_user_query = None

            text = combined_input


        # Record user turn (after clarification merge)
        self.state.add_turn("user", text)

        # Optional cheap greeting handling (NO LLM)
        if not clarification_in_progress and text.strip().lower() in {
            "hi", "hello", "hey"
        }:
            return {
                "type": "GREETING",
                "message": "Hello! How can I help you with EMS data?"
            }

        # -------------------------------------------------
        # Groq-based refinement (NOW WITH RESULT CONTEXT)
        # -------------------------------------------------
        result = refine_with_groq(text, self.state)

        # -------------------------------------------------
        # Clarification path
        # -------------------------------------------------
        if result.get("needs_clarification"):
            # Store clarification context (DO NOT clear yet)
            self.state.pending_clarification_question = result["clarification_question"]
            self.state.pending_user_query = text

            return {
                "type": "CLARIFICATION",
                "message": result["clarification_question"]
            }

        # -------------------------------------------------
        # Analytics path
        # -------------------------------------------------
        refined = result.get("refined_question")
        updates = result.get("state_updates", {})

        # Case 1: clarification just resolved, model didn't restate question
        if not refined and clarification_in_progress:
            refined = text

        # Case 2: no clarification, but model extracted state → input is already precise
        elif not refined and updates:
            refined = text

        if not refined:
            raise ValueError("No refined_question returned")

        # Now it is SAFE to clear clarification state
        self.state.pending_clarification_question = None
        self.state.pending_user_query = None

        # Apply state updates
        for key, value in updates.items():
            if value is not None:
                setattr(self.state, key, value)

        # Record assistant turn for continuity
        self.state.add_turn("assistant", refined)

        return {
            "type": "ANALYTICS",
            "refined_question": refined
        }
    
    def update_query_results(
        self,
        refined_question: str,
        sql: str,
        result_df: pd.DataFrame
    ):
        """
        Update state with query execution results.
        This enables context-aware follow-up questions.
        
        Call this after SQL execution in your main.py or API layer.
        
        Args:
            refined_question: The analytical question that was asked
            sql: The SQL that was executed
            result_df: The pandas DataFrame returned from execution
        """
        # Extract result metadata
        query_type, entities = self._extract_result_metadata(result_df, refined_question)
        
        # Update state
        self.state.update_result_context(
            refined_question=refined_question,
            query_type=query_type,
            result_entities=entities,
            result_count=len(result_df),
            sql_query=sql
        )
    
    def _extract_result_metadata(
        self,
        df: pd.DataFrame,
        question: str
    ) -> tuple[str, list[str]]:
        """
        Extract metadata from query results for context tracking.
        
        Returns:
            (query_type, entity_list) tuple
        """
        if df.empty:
            return "empty_result", []
        
        # Detect query type based on columns and question
        columns = [col.lower() for col in df.columns]
        question_lower = question.lower()
        
        # Vendor queries
        if any(col in columns for col in ['vendor_name', 'full_name']) and 'vendor' in question_lower:
            entity_col = 'vendor_name' if 'vendor_name' in df.columns else 'full_name'
            return "vendor_list", df[entity_col].astype(str).tolist()[:20]  # Max 20 for context
        
        # Account queries
        elif 'account_name' in columns or ('account' in question_lower and any('name' in col for col in columns)):
            entity_col = 'account_name' if 'account_name' in df.columns else df.columns[0]
            return "account_list", df[entity_col].astype(str).tolist()[:20]
        
        # Warehouse queries
        elif 'warehouse_name' in columns or 'warehouse' in question_lower:
            entity_col = 'warehouse_name' if 'warehouse_name' in df.columns else df.columns[0]
            return "warehouse_list", df[entity_col].astype(str).tolist()[:20]
        
        # Invoice queries
        elif 'invoice' in question_lower:
            # Check if it's a count/aggregate or listing
            if len(df) == 1 and any(term in columns for term in ['count', 'total', 'sum', 'avg']):
                # Preserve domain even if no row entities exist
                if 'vendor' in question.lower():
                    return "vendor_aggregate", []
                elif 'account' in question.lower():
                    return "account_aggregate", []
                elif 'warehouse' in question.lower():
                    return "warehouse_aggregate", []
                return "aggregate_result", []
            else:
                return "invoice_list", []
        
        # Generic result
        else:
            # Try to extract entity names from first column if it looks like names
            first_col = df.columns[0]
            if 'name' in first_col.lower():
                return "entity_list", df[first_col].astype(str).tolist()[:20]
            else:
                return "query_result", []