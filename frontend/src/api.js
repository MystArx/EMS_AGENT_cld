import axios from 'axios';

// Point to your FastAPI Backend
const apiClient = axios.create({
  baseURL: 'https://ems-ai-agent.up.railway.app',
  headers: {
    'Content-Type': 'application/json',
  },
});

export default {
  // 1. Send message to refine/clarify
  async sendChat(message, sessionId, isFollowUpMode) {
    const response = await apiClient.post('/api/chat', {
      message,
      session_id: sessionId,
      use_followup_context: isFollowUpMode === true
    });
    return response.data;
  },

  // 2. Request SQL Generation (The 40s wait)
  async generateSQL(refinedQuestion, sessionId, useFollowUpContext = false) {
    const response = await apiClient.post('/api/generate-sql', { 
      refined_question: refinedQuestion, 
      session_id: sessionId,
      use_followup_context: useFollowUpContext
    });
    return response.data;
  },

  // 3. Execute approved SQL
  async executeSQL(sql, refinedQuestion = '', sessionId = '') {
    const response = await apiClient.post('/api/execute-sql', {
      sql,
      refined_question: refinedQuestion,
      session_id: sessionId
    });
    return response.data;
  }
};