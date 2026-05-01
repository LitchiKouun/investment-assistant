<script setup>
import { computed, ref } from 'vue'

const createSession = (title = '新会话') => ({
  id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  title,
  messages: [],
})

const sessions = ref([createSession('市场分析')])
const activeSessionId = ref(sessions.value[0].id)
const inputText = ref('')
const loading = ref(false)

const activeSession = computed(() =>
  sessions.value.find((session) => session.id === activeSessionId.value),
)

const switchSession = (sessionId) => {
  activeSessionId.value = sessionId
}

const newSession = () => {
  const session = createSession()
  sessions.value.unshift(session)
  activeSessionId.value = session.id
}

const updateSessionTitle = (session, fallbackTitle) => {
  if (session.title === '新会话') {
    session.title = fallbackTitle.slice(0, 12) || '新会话'
  }
}

const sendMessage = async () => {
  const text = inputText.value.trim()
  if (!text || loading.value || !activeSession.value) return

  const currentSession = activeSession.value
  currentSession.messages.push({
    role: 'user',
    content: text,
  })
  updateSessionTitle(currentSession, text)
  inputText.value = ''

  loading.value = true
  try {
    const res = await fetch('http://127.0.0.1:8000/analyze', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query: text }),
    })

    if (!res.ok) {
      const errData = await res.json()
      throw new Error(errData.detail || '请求失败')
    }

    const data = await res.json()
    currentSession.messages.push({
      role: 'assistant',
      content: data.result || '暂无返回结果',
    })
  } catch (err) {
    currentSession.messages.push({
      role: 'assistant',
      content: `发生错误：${err.message || '未知错误'}`,
    })
  } finally {
    loading.value = false
  }
}
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
            <span class="session-meta">{{ session.messages.length }} 条消息</span>
          </button>
        </li>
      </ul>
    </aside>

    <main class="chat-main">
      <div class="chat-header">
        <h1>{{ activeSession?.title || '智能助手' }}</h1>
      </div>

      <div class="chat-body">
        <template v-if="activeSession && activeSession.messages.length">
          <div
            v-for="(msg, idx) in activeSession.messages"
            :key="idx"
            class="message"
            :class="msg.role"
          >
            <div class="message-role">
              {{ msg.role === 'user' ? '你' : 'AI' }}
            </div>
            <div class="message-content">{{ msg.content }}</div>
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
  height: 64px;
  border-bottom: 1px solid #e5e7eb;
  background: #fff;
  display: flex;
  align-items: center;
  padding: 0 20px;
}

.chat-header h1 {
  margin: 0;
  font-size: 18px;
  color: #111827;
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