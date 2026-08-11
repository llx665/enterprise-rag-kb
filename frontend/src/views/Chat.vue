<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Promotion, VideoPause, Delete, More } from '@element-plus/icons-vue'
import ChatMessage from '../components/ChatMessage.vue'
import { streamChat } from '../api/chat'
import {
  createSession,
  deleteSession,
  getSessionMessages,
  listSessions,
  renameSession,
} from '../api/sessions'

// ---------- 会话侧栏 ----------
const sessions = ref([])
const sessionLoading = ref(false)
const keyword = ref('')
const activeSessionId = ref(null)

async function loadSessions() {
  sessionLoading.value = true
  try {
    const data = await listSessions({ keyword: keyword.value || undefined })
    sessions.value = data.items
  } finally {
    sessionLoading.value = false
  }
}

async function handleNewSession() {
  if (sending.value) return
  const session = await createSession()
  activeSessionId.value = session.id
  messages.value = []
  await loadSessions()
  // 聚焦输入框
  inputRef.value?.focus()
}

async function selectSession(id) {
  if (sending.value || id === activeSessionId.value) return
  activeSessionId.value = id
  messagesLoading.value = true
  try {
    messages.value = await getSessionMessages(id)
  } finally {
    messagesLoading.value = false
    scrollToBottom(true)
  }
}

async function handleDeleteSession(session) {
  await ElMessageBox.confirm(`确定删除会话「${session.title}」吗？`, '删除确认', {
    type: 'warning',
  })
  await deleteSession(session.id)
  if (activeSessionId.value === session.id) {
    activeSessionId.value = null
    messages.value = []
  }
  await loadSessions()
  ElMessage.success('会话已删除')
}

function handleRenameSession(session) {
  ElMessageBox.prompt('输入新的会话标题', '重命名', {
    inputValue: session.title,
  })
    .then(async ({ value }) => {
      await renameSession(session.id, value)
      await loadSessions()
    })
    .catch(() => {})
}

// ---------- 消息 ----------
const messages = ref([])
const messagesLoading = ref(false)
const input = ref('')
const sending = ref(false)
const inputRef = ref()
const listRef = ref()
let controller = null
// 当前正在流式生成的模型消息（停止/兜底复位时用来关掉生成动画）
let currentBotMsg = null

const activeTitle = computed(
  () => sessions.value.find((s) => s.id === activeSessionId.value)?.title || '新对话'
)

function formatTime(iso) {
  const d = new Date(iso)
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  if (d.toDateString() === now.toDateString()) {
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function scrollToBottom(force = false) {
  nextTick(() => {
    const el = listRef.value
    if (el && (force || sending.value)) {
      el.scrollTop = el.scrollHeight
    }
  })
}

async function sendMessage() {
  const question = input.value.trim()
  if (!question || sending.value) return
  input.value = ''

  // 乐观更新：追加用户消息 + 空的模型消息
  const userMsg = { id: `u-${Date.now()}`, role: 'user', content: question }
  const botMsg = {
    id: `b-${Date.now()}`,
    role: 'assistant',
    content: '',
    citations: [],
    streaming: true,
  }
  messages.value.push(userMsg, botMsg)
  scrollToBottom()

  sending.value = true
  currentBotMsg = botMsg
  const currentSessionId = activeSessionId.value

  controller = streamChat({
    sessionId: currentSessionId,
    question,
    onMeta: (payload) => {
      botMsg.citations = payload.citations || []
    },
    onDelta: (text) => {
      botMsg.content += text
      scrollToBottom()
    },
    onTool: (info) => {
      if (!botMsg.tools) botMsg.tools = []
      botMsg.tools.push(info.display || info.name)
      scrollToBottom()
    },
    onDone: (payload) => {
      botMsg.streaming = false
      botMsg.id = payload.message_id
      botMsg.latency_ms = payload.latency_ms
      botMsg.cached = payload.cached
      if (!currentSessionId) {
        // 首个问题：后端自动创建了会话，回填会话 ID
        activeSessionId.value = payload.session_id
      }
      loadSessions()
    },
    onError: (err) => {
      botMsg.streaming = false
      if (!botMsg.content) {
        botMsg.content = `⚠️ ${err.message}`
      }
    },
    onFinish: () => {
      // 兜底复位：无论流是正常结束、出错还是手动停止，
      // 输入框立即恢复可用，无需刷新页面
      sending.value = false
      if (currentBotMsg) {
        currentBotMsg.streaming = false
        currentBotMsg = null
      }
    },
  })
}

function stopStream() {
  if (controller) {
    controller.abort()
    controller = null
  }
  // 点击「停止」后立即恢复输入（onFinish 兜底也会执行）
  sending.value = false
  if (currentBotMsg) {
    currentBotMsg.streaming = false
    currentBotMsg = null
  }
}

async function handleSend() {
  if (sending.value) {
    stopStream()
    return
  }
  await sendMessage()
}

function handleKeydown(e) {
  // Enter 发送，Shift+Enter 换行
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

onMounted(() => {
  loadSessions()
})
</script>

<template>
  <div class="chat-page">
    <!-- 会话侧栏 -->
    <div class="session-panel">
      <div class="session-header">
        <el-button type="primary" :icon="Plus" class="new-btn" @click="handleNewSession">
          新建会话
        </el-button>
        <el-input v-model="keyword" placeholder="搜索会话" :prefix-icon="Search" clearable size="small" @change="loadSessions" />
      </div>

      <div v-loading="sessionLoading" class="session-list">
        <div
          v-for="session in sessions"
          :key="session.id"
          class="session-item"
          :class="{ active: session.id === activeSessionId }"
          @click="selectSession(session.id)"
        >
          <div class="session-title">{{ session.title }}</div>
          <div class="session-actions">
            <span class="session-time">{{ formatTime(session.last_message_at) }}</span>
            <el-dropdown trigger="click" @command="(cmd) => cmd === 'rename' ? handleRenameSession(session) : handleDeleteSession(session)">
              <el-icon class="session-more"><More /></el-icon>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
        <el-empty v-if="!sessions.length && !sessionLoading" description="暂无会话" :image-size="60" />
      </div>
    </div>

    <!-- 聊天区 -->
    <div class="chat-panel">
      <div class="chat-header">
        <span class="chat-title">{{ activeTitle }}</span>
        <el-tag v-if="sending" type="warning" size="small">生成中…</el-tag>
      </div>

      <div ref="listRef" v-loading="messagesLoading" class="message-list">
        <div v-if="!messages.length && !messagesLoading" class="empty-state">
          <div class="empty-icon">💬</div>
          <p>向知识库提问，获取基于商品资料的回答</p>
          <p class="empty-tip">例如：这款手机的电池续航怎么样？</p>
        </div>
        <ChatMessage v-for="msg in messages" :key="msg.id" :message="msg" />
      </div>

      <div class="input-area">
        <el-input
          ref="inputRef"
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          placeholder="请输入你的问题，Enter 发送，Shift+Enter 换行"
          :disabled="sending"
          @keydown="handleKeydown"
        />
        <div class="input-actions">
          <span v-if="sending" class="hint">正在生成回答…</span>
          <el-button type="primary" :icon="sending ? VideoPause : Promotion" @click="handleSend">
            {{ sending ? '停止' : '发送' }}
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  height: 100%;
}

/* ---------- 会话侧栏 ---------- */
.session-panel {
  width: 250px;
  border-right: 1px solid #e5e7eb;
  background: #fff;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.session-header {
  padding: 16px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  border-bottom: 1px solid #f3f4f6;
}

.new-btn {
  width: 100%;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: background 0.15s;
}

.session-item:hover {
  background: #f3f4f6;
}

.session-item.active {
  background: #eff6ff;
}

.session-title {
  font-size: 13px;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
}

.session-time {
  font-size: 11px;
  color: #9ca3af;
}

.session-more {
  font-size: 14px;
  color: #9ca3af;
  cursor: pointer;
  visibility: hidden;
}

.session-item:hover .session-more,
.session-item.active .session-more {
  visibility: visible;
}

/* ---------- 聊天区 ---------- */
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-header {
  height: 52px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.chat-title {
  font-weight: 600;
  color: #1f2937;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
}

.empty-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.empty-state p {
  margin: 4px 0;
  font-size: 14px;
}

.empty-tip {
  font-size: 12px;
  color: #d1d5db;
}

.input-area {
  padding: 16px 24px 20px;
  background: #fff;
  border-top: 1px solid #e5e7eb;
}

.input-area :deep(.el-textarea__inner) {
  border-radius: 10px;
  font-size: 14px;
}

.input-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  margin-top: 10px;
  gap: 12px;
}

.hint {
  font-size: 12px;
  color: #9ca3af;
}
</style>
