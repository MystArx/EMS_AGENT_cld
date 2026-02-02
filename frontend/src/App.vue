<template>
  <!-- SPLASH -->
  <transition name="fade">
    <div v-if="!systemReady" class="splash-screen">
      <div class="loader-ring"></div>
      <h1>EMS AI Agent</h1>
      <p class="status-text">{{ systemStatus }}</p>
    </div>
  </transition>

  <!-- APP -->
  <div v-if="systemReady" class="app-layout">

    <!-- SIDEBAR -->
    <aside class="sidebar">
      <div class="sidebar-top">
        <div class="brand">
          <div class="logo">EMS</div>
          <div class="brand-text">
            <strong>EMS Agent</strong>
            <span>Analytics Intelligence</span>
          </div>
        </div>

        <div class="menu-section">
          <div class="menu-label">SYSTEM CONTROLS</div>

          <div class="control-group">
            <label>User Role</label>
            <select v-model="userRole">
              <option value="user">Business User</option>
              <option value="admin">Data Admin</option>
            </select>
          </div>

          <button class="btn-reset" @click="resetSession">
            ↺ Reset Session
          </button>
        </div>
      </div>

      <div class="sidebar-footer">
        <span class="dot"></span>
        <div>
          <strong>System Online</strong>
          <small>Model active</small>
        </div>
      </div>
    </aside>

    <!-- MAIN -->
    <main class="main">

      <!-- EMPTY STATE -->
      <div v-if="chatHistory.length === 0" class="empty-state">
        <div class="empty-shell">
          <h1>Ask anything about your EMS data</h1>
          <p>
            Invoices, vendors, regions, spend analysis, anomaly detection.
          </p>
          <div class="suggestions">
            <span @click="quickAsk('Show top 5 vendors by spend')">Top vendors</span>
            <span @click="quickAsk('Invoices created today')">Invoices today</span>
          </div>
        </div>
      </div>

      <!-- CHAT -->
      <div v-else class="messages" ref="chatWindow">
        <div
          v-for="(msg, i) in chatHistory"
          :key="i"
          :class="['msg-row', msg.role]"
        >
          <div class="avatar">{{ msg.role === 'assistant' ? 'AI' : 'U' }}</div>

          <div class="msg-content">
            <div
              v-if="msg.content"
              class="bubble"
              :class="{ 'error-bubble': msg.isError }"
              v-html="renderMarkdown(msg.content)"
            ></div>

            <!-- SQL REVIEW -->
            <div v-if="msg.pendingSQL && userRole === 'admin'" class="sql-card">
              <div class="sql-header">SQL REVIEW REQUIRED</div>
              <textarea v-model="msg.pendingSQL" spellcheck="false" readonly></textarea>
              <div class="sql-actions">
                <button class="btn-primary" @click="approveSQL(i)">✓ Run</button>
                <button class="btn-warning" @click="openCorrectionModal(i)">✗ Correct</button>
                <button class="btn-ghost" @click="discardSQL(i)">Discard</button>
              </div>
            </div>

            <!-- TABLE -->
            <div v-if="msg.tableData" class="table-card">
              <div class="table-header">
                <span>Result ({{ msg.tableData.row_count }} rows)</span>
                <span>{{ msg.tableData.execution_time.toFixed(3) }}s</span>
              </div>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th v-for="c in msg.tableData.columns" :key="c">{{ c }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(r, ri) in msg.tableData.data" :key="ri">
                      <td v-for="c in msg.tableData.columns" :key="c">
                        {{ r[c] }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- FEEDBACK BUTTONS (Business Users Only) -->
            <div v-if="msg.tableData && msg.canFeedback && userRole === 'user'" class="feedback-section">
              <div class="feedback-label">Was this result correct?</div>
              <div class="feedback-buttons">
                <button @click="submitFeedback(i, 'correct')" class="btn-feedback correct">
                  ✓ Correct
                </button>
                <button @click="submitFeedback(i, 'wrong')" class="btn-feedback wrong">
                  ✗ Wrong Result
                </button>
              </div>
              <div v-if="msg.feedbackMessage" class="feedback-message">
                {{ msg.feedbackMessage }}
              </div>
            </div>

            <div v-if="msg.error" class="error-badge">
              {{ msg.error }}
            </div>
          </div>
        </div>

        <!-- TYPING -->
        <div v-if="loading" class="msg-row assistant">
          <div class="avatar">AI</div>
          <div class="bubble typing">{{ loadingText }}</div>
        </div>
      </div>

      <!-- INPUT -->
      <!-- INPUT -->
      <div class="input-bar">
        <div class="input-container">
          <div class="mode-toggle">
            <button 
              @click="followUpMode = false" 
              :class="['toggle-btn', { active: !followUpMode }]"
              title="Ask a new, independent question"
            >
              🆕 New Question
            </button>
            <button 
              @click="followUpMode = true" 
              :class="['toggle-btn', { active: followUpMode }]"
              title="Ask a follow-up using previous results"
            >
              🔗 Follow-up
            </button>
          </div>
          
          <div class="input-wrapper">
            <input
              ref="mainInput"
              v-model="userInput"
              @keyup.enter.prevent="sendMessage"
              :placeholder="followUpMode ? 'Ask about the previous results…' : 'Ask a business question…'"
              :disabled="loading"
            />
            <button @click="sendMessage" :disabled="loading || !userInput.trim()">→</button>
          </div>
        </div>
      </div>

    </main>
  </div>

  <!-- CORRECTION MODAL -->
  <div v-if="showCorrectionModal" class="modal-overlay" @click.self="closeCorrectionModal">
    <div class="modal-box">
      <div class="modal-header">
        <h3>Correct SQL & Teach System</h3>
        <button @click="closeCorrectionModal" class="btn-close">×</button>
      </div>
      
      <div class="modal-body">
        <label>Question:</label>
        <div class="readonly-box">{{ correctionData.question }}</div>
        
        <label>Wrong SQL (generated):</label>
        <textarea v-model="correctionData.incorrectSQL" readonly rows="5" spellcheck="false"></textarea>
        
        <label>Corrected SQL:</label>
        <textarea v-model="correctionData.correctedSQL" rows="7" placeholder="Enter correct SQL..." spellcheck="false"></textarea>
        
        <label>What was wrong? (optional):</label>
        <textarea v-model="correctionData.notes" rows="2" placeholder="e.g., Used NOW() instead of updated_at" spellcheck="false"></textarea>
      </div>
      
      <div class="modal-footer">
        <button @click="closeCorrectionModal" class="btn-ghost">Cancel</button>
        <button @click="submitCorrection" class="btn-primary" :disabled="submittingCorrection || !correctionData.correctedSQL.trim()">
          {{ submittingCorrection ? 'Saving...' : '💾 Save & Learn' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import api from './api'
import { v4 as uuidv4 } from 'uuid'
import { marked } from 'marked'

export default {
  data() {
    return {
      systemReady: false,
      systemStatus: 'Connecting…',
      sessionId: uuidv4(),
      userRole: 'user',
      userInput: '',
      loading: false,
      loadingText: 'Thinking…',
      chatHistory: [],
      feedbackGiven: new Set(),
      followUpMode: false,

      // Correction modal
      showCorrectionModal: false,
      submittingCorrection: false,
      correctionData: {
        messageIndex: null,
        question: '',
        incorrectSQL: '',
        correctedSQL: '',
        notes: ''
      }
    }
  },

  mounted() {
    this.waitForBackend()
  },

  methods: {
    /* ---------------- SYSTEM ---------------- */

    async waitForBackend() {
      const poll = setInterval(async () => {
        try {
          const r = await fetch('http://127.0.0.1:8000/api/status')
          const d = await r.json()
          this.systemStatus = d.message

          if (d.ready) {
            this.systemReady = true
            clearInterval(poll)
            this.$nextTick(() => this.$refs.mainInput?.focus())
          }
        } catch {
          this.systemStatus = 'Waiting for backend…'
        }
      }, 2000)
    },

    resetSession() {
      this.sessionId = uuidv4()
      this.chatHistory = []
      this.$nextTick(() => this.$refs.mainInput?.focus())
    },

    quickAsk(text) {
      this.userInput = text
      this.sendMessage()
    },

    renderMarkdown(t) {
      return marked.parse(t || '')
    },

    scrollBottom() {
      this.$nextTick(() => {
        const el = this.$refs.chatWindow
        if (el) el.scrollTop = el.scrollHeight
      })
    },

    /* ---------------- CHAT ---------------- */

    async sendMessage() {
      if (!this.userInput.trim()) return

      const text = this.userInput
      this.chatHistory.push({ role: 'user', content: text })
      this.userInput = ''
      this.loading = true
      this.scrollBottom()

      try {
        const res = await api.sendChat(text, this.sessionId)
        if (res.type === 'ANALYTICS') {
          await this.handleDataQuery(res.refined_question)
        } else {
          this.chatHistory.push({ role: 'assistant', content: res.message })
        }
      } catch (e) {
        this.chatHistory.push({
          role: 'assistant',
          content: `**System Error:** ${e.message}`,
          isError: true
        })
      } finally {
        this.loading = false
        this.scrollBottom()
      }
    },

    async handleDataQuery(q) {
      const i =
        this.chatHistory.push({
          role: 'assistant',
          content: `Checking **"${q}"**…`,
          refinedQuestion: q
        }) - 1

      try {
        // Pass follow-up mode to backend
        const sql = await api.generateSQL(q, this.sessionId, this.followUpMode)

        if (this.userRole === 'admin') {
          this.chatHistory[i].pendingSQL = sql.sql
        } else {
          await this.runQuery(i, sql.sql)
        }
      } catch (e) {
        this.chatHistory[i].error = e.message
      }
    },

    async approveSQL(i) {
      const sql = this.chatHistory[i].pendingSQL
      this.chatHistory[i].pendingSQL = null
      await this.runQuery(i, sql)
    },

    discardSQL(i) {
      this.chatHistory[i].pendingSQL = null
      this.chatHistory[i].content = 'Query discarded.'
    },

    async runQuery(i, sql) {
      try {
        const r = await api.executeSQL(
          sql,
          this.chatHistory[i].refinedQuestion,
          this.sessionId
        )

        this.chatHistory[i].tableData = r
        this.chatHistory[i].content = null
        this.chatHistory[i].canFeedback = true
        this.chatHistory[i].executedSQL = sql
      } catch (e) {
        this.chatHistory[i].error = e.message
      }
    },

    /* ---------------- FEEDBACK ---------------- */

    async submitFeedback(messageIndex, feedbackType) {
      if (this.feedbackGiven.has(messageIndex)) return

      const msg = this.chatHistory[messageIndex]

      const feedbackData = {
        timestamp: new Date().toISOString(),
        session_id: this.sessionId,
        feedback_type: feedbackType,
        user_question:
          this.chatHistory[messageIndex - 1]?.content || 'Unknown',
        refined_question: msg.refinedQuestion,
        generated_sql: msg.executedSQL,
        result_count: msg.tableData?.row_count || 0,
        chat_state: {
          previous_query: this.getPreviousQueryContext(messageIndex),
          is_followup: this.isFollowupQuestion(messageIndex)
        },
        user_role: this.userRole
      }

      try {
        await fetch('http://127.0.0.1:8000/api/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(feedbackData)
        })

        this.feedbackGiven.add(messageIndex)
        msg.canFeedback = false
        msg.feedbackMessage =
          feedbackType === 'correct'
            ? '✓ Thanks! Your feedback helps improve the system.'
            : '✗ Feedback logged. Our team will review this query.'

        setTimeout(() => {
          msg.feedbackMessage = null
        }, 3000)
      } catch (error) {
        console.error('Feedback failed:', error)
        alert('Failed to submit feedback.')
      }
    },

    getPreviousQueryContext(currentIndex) {
      for (let i = currentIndex - 1; i >= 0; i--) {
        const msg = this.chatHistory[i]
        if (msg.role === 'assistant' && msg.tableData) {
          return {
            question: msg.refinedQuestion,
            result_count: msg.tableData.row_count,
            sql: msg.executedSQL
          }
        }
      }
      return null
    },

    isFollowupQuestion(messageIndex) {
      const userMsg = this.chatHistory[messageIndex - 1]?.content || ''
      const followupKeywords = [
        'which',
        'those',
        'them',
        'they',
        'that',
        'these',
        'which months',
        'missing months'
      ]
      return followupKeywords.some(k =>
        userMsg.toLowerCase().includes(k)
      )
    },

    /* ---------------- CORRECTION MODAL ---------------- */

    openCorrectionModal(messageIndex) {
      const msg = this.chatHistory[messageIndex]

      this.correctionData = {
        messageIndex,
        question: msg.refinedQuestion || 'Unknown question',
        incorrectSQL: msg.pendingSQL,
        correctedSQL: msg.pendingSQL,
        notes: ''
      }

      this.showCorrectionModal = true
    },

    closeCorrectionModal() {
      this.showCorrectionModal = false
      this.correctionData = {
        messageIndex: null,
        question: '',
        incorrectSQL: '',
        correctedSQL: '',
        notes: ''
      }
    },

    async submitCorrection() {
      if (!this.correctionData.correctedSQL.trim()) {
        alert('Please enter the corrected SQL')
        return
      }

      this.submittingCorrection = true

      try {
        const r = await fetch(
          'http://127.0.0.1:8000/api/admin/correct-sql',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              refined_question: this.correctionData.question,
              incorrect_sql: this.correctionData.incorrectSQL,
              corrected_sql: this.correctionData.correctedSQL,
              correction_notes: this.correctionData.notes
            })
          }
        )

        const data = await r.json()
        if (!data.success) throw new Error(data.message)

        const i = this.correctionData.messageIndex
        this.chatHistory[i].pendingSQL = null
        await this.runQuery(i, this.correctionData.correctedSQL)

        this.closeCorrectionModal()
      } catch (e) {
        console.error('Correction failed:', e)
        alert('Failed to save correction')
      } finally {
        this.submittingCorrection = false
      }
    }
  }
}
</script>

<!-- GLOBAL -->
<style>
html, body {
  width: 100%;
  height: 100%;
  margin: 0;
  overflow: hidden;
  background: #09090b;
}

:root {
  --bg-dark: #09090b;
  --bg-panel: #18181b;
  --bg-sidebar: #000000;
  --border: #27272a;
  --accent: #2563eb;
  --text-main: #e4e4e7;
  --text-muted: #a1a1aa;
}
</style>

<!-- SCOPED -->
<style scoped>
* { box-sizing: border-box; }

.app-layout {
  width: 100vw;
  height: 100vh;
  display: flex;
  overflow: hidden;
  background: var(--bg-dark);
  color: var(--text-main);
  font-family: Inter, system-ui, sans-serif;
}

/* SIDEBAR */
.sidebar {
  width: 280px;
  flex-shrink: 0;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  padding: 24px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.brand { display: flex; gap: 12px; align-items: center; margin-bottom: 32px; }
.logo {
  width: 36px; height: 36px; border-radius: 8px;
  background: var(--accent); color: white;
  display: flex; align-items: center; justify-content: center;
  font-weight: 800;
}

.menu-label {
  font-size: 0.7rem;
  letter-spacing: 0.1em;
  color: #52525b;
  margin-bottom: 12px;
}

.control-group label {
  font-size: 0.8rem;
  color: var(--text-muted);
}

select {
  width: 100%;
  margin-top: 6px;
  padding: 8px 10px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  color: white;
  border-radius: 6px;
}

.btn-reset {
  margin-top: 16px;
  padding: 10px;
  width: 100%;
  background: transparent;
  border: 1px dashed #3f3f46;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 6px;
}

.btn-reset:hover {
  border-color: #52525b;
}

.sidebar-footer {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 0.8rem;
}

.dot {
  width: 8px;
  height: 8px;
  background: #22c55e;
  border-radius: 50%;
}

/* MAIN */
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #09090b 40%);
}

/* EMPTY */
.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-shell {
  max-width: 520px;
  text-align: center;
}

.empty-shell h1 {
  font-size: 2rem;
  margin-bottom: 12px;
}

.empty-shell p {
  color: var(--text-muted);
  margin-bottom: 20px;
}

.suggestions span {
  margin: 0 6px;
  padding: 8px 14px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 20px;
  cursor: pointer;
  display: inline-block;
}

.suggestions span:hover {
  border-color: var(--accent);
}

/* MESSAGES */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 32px 40px 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.msg-row {
  display: flex;
  gap: 16px;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}

.msg-row.user { flex-direction: row-reverse; }

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: var(--bg-panel);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  flex-shrink: 0;
}

.msg-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* BUBBLES */
.bubble {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  padding: 14px 18px;
  border-radius: 12px;
  line-height: 1.6;
}

.msg-row.user .bubble {
  background: var(--accent);
  border: none;
  color: white;
}

.error-bubble {
  border-color: #ef4444;
  background: #450a0a;
}

/* SQL */
.sql-card {
  border: 1px solid #f59e0b;
  border-radius: 8px;
  overflow: hidden;
}

.sql-header {
  background: #451a03;
  color: #fbbf24;
  padding: 8px 12px;
  font-size: 0.75rem;
  font-weight: 600;
}

.sql-card textarea {
  width: 100%;
  height: 100px;
  background: #1c1917;
  color: #fbbf24;
  border: none;
  padding: 12px;
  resize: none;
  font-family: 'Monaco', 'Courier New', monospace;
  font-size: 13px;
}

.sql-actions {
  padding: 10px;
  background: var(--bg-panel);
  display: flex;
  gap: 10px;
}

.btn-primary {
  padding: 8px 16px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}

.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-warning {
  padding: 8px 16px;
  background: #f59e0b;
  color: #000;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}

.btn-warning:hover {
  background: #d97706;
}

.btn-ghost {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  border-radius: 6px;
  cursor: pointer;
}

.btn-ghost:hover {
  border-color: #52525b;
}

/* TABLE */
.table-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.table-header {
  padding: 8px 12px;
  background: var(--bg-panel);
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
}

.table-wrap {
  overflow-x: auto;
  max-height: 400px;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

th, td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}

th {
  background: var(--bg-panel);
  font-weight: 600;
  position: sticky;
  top: 0;
}

.error-badge {
  padding: 8px 12px;
  background: #450a0a;
  border: 1px solid #ef4444;
  border-radius: 6px;
  color: #fca5a5;
  font-size: 0.85rem;
}

/* INPUT */
/* INPUT */
.input-bar {
  padding: 24px;
  border-top: 1px solid var(--border);
}

.input-container {
  max-width: 900px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mode-toggle {
  display: flex;
  gap: 8px;
  padding: 4px;
  background: var(--bg-panel);
  border-radius: 8px;
  width: fit-content;
}

.toggle-btn {
  padding: 6px 14px;
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 500;
  transition: all 0.2s;
}

.toggle-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-main);
}

.toggle-btn.active {
  background: var(--accent);
  color: white;
}

.input-wrapper {
  display: flex;
  gap: 10px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  padding: 6px;
  border-radius: 10px;
}

.input-wrapper input {
  flex: 1;
  background: transparent;
  border: none;
  color: white;
  font-size: 1rem;
  padding: 8px 12px;
}

.input-wrapper input:focus {
  outline: none;
}

.input-wrapper button {
  width: 40px;
  background: var(--accent);
  border: none;
  color: white;
  cursor: pointer;
  border-radius: 6px;
  font-size: 18px;
}

.input-wrapper button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* MODAL */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}

.modal-box {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: 90%;
  max-width: 700px;
  max-height: 85vh;
  overflow-y: auto;
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}

.btn-close {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 28px;
  cursor: pointer;
  padding: 0;
  width: 32px;
  height: 32px;
  line-height: 1;
}

.btn-close:hover {
  color: var(--text-main);
}

.modal-body {
  padding: 20px;
}

.modal-body label {
  display: block;
  margin-top: 16px;
  margin-bottom: 6px;
  font-size: 0.85rem;
  color: var(--text-muted);
  font-weight: 500;
}

.modal-body label:first-child {
  margin-top: 0;
}

.readonly-box {
  padding: 10px 12px;
  background: #09090b;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-muted);
  font-size: 0.9rem;
}

.modal-body textarea {
  width: 100%;
  padding: 10px 12px;
  background: #09090b;
  border: 1px solid var(--border);
  color: white;
  border-radius: 6px;
  font-family: 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  resize: vertical;
}

.modal-body textarea[readonly] {
  color: var(--text-muted);
  background: #0a0a0a;
}

.modal-body textarea:not([readonly]):focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2);
}

.modal-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

/* SPLASH */
.splash-screen {
  position: fixed;
  inset: 0;
  background: black;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: white;
}

.loader-ring {
  width: 50px;
  height: 50px;
  border: 4px solid #333;
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 20px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

/* Add these to your existing styles */

.feedback-section {
  margin-top: 12px;
  padding: 12px 16px;
  background: rgba(39, 39, 42, 0.5);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.feedback-label {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.feedback-buttons {
  display: flex;
  gap: 10px;
}

.btn-feedback {
  padding: 8px 18px;
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 500;
  transition: all 0.2s;
  background: transparent;
}

.btn-feedback.correct {
  color: #22c55e;
  border-color: #22c55e;
}

.btn-feedback.correct:hover {
  background: #22c55e;
  color: #000;
}

.btn-feedback.wrong {
  color: #ef4444;
  border-color: #ef4444;
}

.btn-feedback.wrong:hover {
  background: #ef4444;
  color: white;
}

.feedback-message {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.85rem;
  background: var(--bg-dark);
  color: var(--text-muted);
  animation: fadeIn 0.3s;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-5px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>