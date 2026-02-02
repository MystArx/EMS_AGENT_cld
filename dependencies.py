# backend/dependencies.py

from services.api.chat_controller import ChatController
from services.api.sql_client import SQLClient

# Global storage
sessions = {}
sql_client_instance = None

def get_sql_client():
    global sql_client_instance
    if sql_client_instance is None:
        print(">>> STARTUP: Loading SQL Client...")
        sql_client_instance = SQLClient()
        
        # --- WARM-UP LOGIC ---
        print(">>> STARTUP: Warming up LLM...")
        try:
            # We run a dummy generation so the model loads into VRAM immediately
            sql_client_instance.generate_sql("select 1") 
            print(">>> STARTUP: Warm-up complete.")
        except Exception as e:
            print(f">>> WARNING: Warm-up failed: {e}")
            
    return sql_client_instance

def get_chat_controller(session_id: str) -> ChatController:
    if session_id not in sessions:
        # Create a new controller for new session IDs
        sessions[session_id] = ChatController(session_id=session_id)
    return sessions[session_id]