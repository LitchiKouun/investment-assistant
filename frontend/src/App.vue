<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const API_BASE = 'http://127.0.0.1:8000'

marked.setOptions({ breaks: true, gfm: true })

function renderAssistantMarkdown(text) {
  if (!text) return ''
  const html = marked(String(text), { async: false })
  return DOMPurify.sanitize(typeof html === 'string' ? html : String(html))
}

const sessions = ref([])
const activeSessionId = ref('')
const inputText = ref('')
const loading = ref(false)
const bootError = ref('')
const chatBodyRef = ref(null)

const activeSession = computed(() =>
  sessions.value.find((session) => session.id === activeSessionId.value),
)

const mapMessage = (m) => ({
  id: m.id,
  role: m.role,
  content: m.content,
})

async function fetchJson(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* ignore */
    }
    throw new Error(detail || '请求失败')
  }
  if (res.status === 204) return null
  return res.json()
}

async function refreshConversationList() {
  const rows = await fetchJson('/conversations')
  sessions.value = rows.map((r) => ({
    id: r.id,
    title: r.title,
    message_count: r.message_count,
    messages: [],
  }))
}

async function loadConversationDetail(sessionId) {
  const detail = await fetchJson(`/conversations/${sessionId}`)
  const s = sessions.value.find((x) => x.id === sessionId)
  if (!s) return
  s.title = detail.title
  s.message_count = detail.messages?.length ?? 0
  s.messages = (detail.messages || []).map(mapMessage)
}

const switchSession = async (sessionId) => {
  activeSessionId.value = sessionId
  try {
    await loadConversationDetail(sessionId)
  } catch (e) {
    bootError.value = e.message || String(e)
  }
}

const newSession = async () => {
  try {
    bootError.value = ''
    const detail = await fetchJson('/conversations', {
      method: 'POST',
      body: JSON.stringify({ title: '新会话' }),
    })
    await refreshConversationList()
    activeSessionId.value = detail.id
    await loadConversationDetail(detail.id)
  } catch (e) {
    bootError.value = e.message || String(e)
  }
}

async function scrollChatToBottom() {
  await nextTick()
  const el = chatBodyRef.value
  if (el) el.scrollTop = el.scrollHeight
}

const sendMessage = async () => {
  const text = inputText.value.trim()
  if (!text || loading.value || !activeSession.value) return

  const currentSession = activeSession.value
  const convId = currentSession.id

  inputText.value = ''
  loading.value = true

  const userMsg = {
    id: `local-${Date.now()}`,
    role: 'user',
    content: text,
  }
  const assistantMsg = {
    id: `local-asst-${Date.now()}`,
    role: 'assistant',
    content: '',
    streaming: true,
  }
  let didStartStream = false

  try {
    const res = await fetch(`${API_BASE}/conversations/${convId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: text }),
    })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } catch {
        /* ignore */
      }
      throw new Error(detail || '请求失败')
    }

    currentSession.messages.push(userMsg)
    currentSession.message_count = (currentSession.message_count || 0) + 1
    currentSession.messages.push(assistantMsg)
    didStartStream = true

    const reader = res.body?.getReader()
    if (!reader) throw new Error('无法读取响应流')

    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed) continue
        let evt
        try {
          evt = JSON.parse(trimmed)
        } catch {
          continue
        }
        if (evt.type === 'delta' && typeof evt.text === 'string') {
          assistantMsg.content += evt.text
          void scrollChatToBottom()
        } else if (evt.type === 'error') {
          const m = typeof evt.message === 'string' ? evt.message : JSON.stringify(evt.message)
          assistantMsg.content += assistantMsg.content ? `\n\n错误：${m}` : `发生错误：${m}`
        }
      }
    }
    assistantMsg.streaming = false
  } catch (err) {
    if (currentSession.messages.includes(assistantMsg)) {
      assistantMsg.streaming = false
      assistantMsg.content =
        assistantMsg.content ||
        `发生错误：${err?.message || String(err)}`
    } else {
      currentSession.messages.push({
        id: `local-err-${Date.now()}`,
        role: 'assistant',
        content: `发生错误：${err?.message || String(err)}`,
      })
    }
  } finally {
    loading.value = false
    if (didStartStream) {
      try {
        await refreshConversationList()
        await loadConversationDetail(convId)
      } catch {
        /* ignore sync errors */
      }
    }
    void scrollChatToBottom()
  }
}

onMounted(async () => {
  try {
    bootError.value = ''
    let rows = await fetchJson('/conversations')
    if (!rows.length) {
      await fetchJson('/conversations', {
        method: 'POST',
        body: JSON.stringify({ title: '市场分析' }),
      })
      rows = await fetchJson('/conversations')
    }
    sessions.value = rows.map((r) => ({
      id: r.id,
      title: r.title,
      message_count: r.message_count,
      messages: [],
    }))
    activeSessionId.value = rows[0].id
    await loadConversationDetail(rows[0].id)
  } catch (e) {
    bootError.value = e.message || String(e)
  }
})
</script>

<template>
  <div class="chat-layout">
    <aside class="sidebar">
      <button class="new-chat-btn" @click="newSession">+ 新建会话</button>
      <ul class="session-list">
        <li v-for="session in sessions" :key="session.id">
          <button
            class="session-item"
            :class="{ active: session.id === activeSessionId }"
            @click="switchSession(session.id)"
          >
            <span class="session-title">{{ session.title }}</span>
            <span class="session-meta">{{ session.message_count ?? session.messages.length }} 条消息</span>
          </button>
        </li>
      </ul>
    </aside>

    <main class="chat-main">
      <div class="chat-header">
        <h1>{{ activeSession?.title || '智能助手' }}</h1>
        <p v-if="bootError" class="boot-error">{{ bootError }}</p>
      </div>

      <div ref="chatBodyRef" class="chat-body">
        <template v-if="activeSession && activeSession.messages.length">
          <div
            v-for="msg in activeSession.messages"
            :key="msg.id"
            class="message"
            :class="msg.role"
          >
            <div class="message-role">
              {{ msg.role === 'user' ? '你' : 'AI' }}
            </div>
            <div
              v-if="msg.role === 'user'"
              class="message-content"
            >{{ msg.content }}</div>
            <div
              v-else
              class="message-content markdown-body"
              v-html="renderAssistantMarkdown(msg.content)"
            />
            <div v-if="msg.role === 'assistant' && msg.streaming" class="stream-cursor" aria-hidden="true" />
          </div>
        </template>
        <div v-else class="empty-tip">
          开始提问吧，例如：帮我分析一下新能源板块近期趋势。
        </div>
      </div>

      <div class="chat-input-wrap">
        <textarea
          v-model="inputText"
          class="chat-input"
          rows="3"
          placeholder="输入你的问题，按发送提交"
          @keydown.enter.exact.prevent="sendMessage"
        />
        <button class="send-btn" :disabled="loading" @click="sendMessage">
          {{ loading ? '发送中...' : '发送' }}
        </button>
      </div>
    </main>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  width: 100%;
  min-height: 100vh;
  background: #f5f7fb;
}

.sidebar {
  width: 280px;
  padding: 16px;
  border-right: 1px solid #e5e7eb;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.new-chat-btn {
  height: 40px;
  border: none;
  border-radius: 10px;
  background: #3763ff;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
}

.session-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
}

.session-item {
  width: 100%;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 10px;
  padding: 10px 12px;
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-item.active {
  border-color: #3763ff;
  background: #eef3ff;
}

.session-title {
  color: #111827;
  font-weight: 600;
}

.session-meta {
  color: #6b7280;
  font-size: 12px;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-header {
  min-height: 64px;
  border-bottom: 1px solid #e5e7eb;
  background: #fff;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 20px;
}

.chat-header h1 {
  margin: 0;
  font-size: 18px;
  color: #111827;
}

.boot-error {
  margin: 0 0 0 16px;
  font-size: 13px;
  color: #b91c1c;
  flex: 1;
  min-width: 0;
}

.chat-body {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.message {
  max-width: 80%;
  padding: 12px 14px;
  border-radius: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  position: relative;
}

.message :deep(.markdown-body) {
  white-space: normal;
}

.message :deep(.markdown-body h1),
.message :deep(.markdown-body h2),
.message :deep(.markdown-body h3) {
  margin: 0.6em 0 0.35em;
  font-weight: 700;
  line-height: 1.3;
}

.message :deep(.markdown-body h1) {
  font-size: 1.25rem;
}

.message :deep(.markdown-body h2) {
  font-size: 1.1rem;
}

.message :deep(.markdown-body h3) {
  font-size: 1rem;
}

.message :deep(.markdown-body p) {
  margin: 0.4em 0;
}

.message :deep(.markdown-body p:first-child) {
  margin-top: 0;
}

.message :deep(.markdown-body p:last-child) {
  margin-bottom: 0;
}

.message :deep(.markdown-body ul),
.message :deep(.markdown-body ol) {
  margin: 0.35em 0;
  padding-left: 1.25rem;
}

.message :deep(.markdown-body code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.9em;
  background: rgba(0, 0, 0, 0.06);
  padding: 0.1em 0.35em;
  border-radius: 4px;
}

.message :deep(.markdown-body pre) {
  margin: 0.5em 0;
  padding: 10px 12px;
  overflow-x: auto;
  background: #f3f4f6;
  border-radius: 8px;
  font-size: 13px;
}

.message :deep(.markdown-body pre code) {
  background: none;
  padding: 0;
}

.message :deep(.markdown-body blockquote) {
  margin: 0.5em 0;
  padding-left: 0.75em;
  border-left: 3px solid #d1d5db;
  color: #4b5563;
}

.message :deep(.markdown-body table) {
  border-collapse: collapse;
  font-size: 13px;
  margin: 0.5em 0;
}

.message :deep(.markdown-body th),
.message :deep(.markdown-body td) {
  border: 1px solid #e5e7eb;
  padding: 6px 8px;
}

.message :deep(.markdown-body th) {
  background: #f9fafb;
}

.stream-cursor {
  display: inline-block;
  width: 6px;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: #3763ff;
  border-radius: 1px;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.message.user {
  margin-left: auto;
  background: #3763ff;
  color: #fff;
}

.message.assistant {
  background: #fff;
  border: 1px solid #e5e7eb;
  color: #111827;
}

.message-role {
  font-size: 12px;
  opacity: 0.8;
  margin-bottom: 6px;
}

.empty-tip {
  margin: auto;
  color: #6b7280;
}

.chat-input-wrap {
  border-top: 1px solid #e5e7eb;
  padding: 16px 20px;
  background: #fff;
  display: flex;
  gap: 12px;
}

.chat-input {
  flex: 1;
  resize: none;
  border: 1px solid #d1d5db;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 14px;
  outline: none;
}

.chat-input:focus {
  border-color: #3763ff;
}

.send-btn {
  width: 92px;
  border: none;
  border-radius: 10px;
  background: #3763ff;
  color: #fff;
  cursor: pointer;
}

.send-btn:disabled {
  background: #9ca3af;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .chat-layout {
    flex-direction: column;
  }

  .sidebar {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid #e5e7eb;
    max-height: 220px;
  }
}
</style>