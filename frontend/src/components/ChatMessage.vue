<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, User, Loading } from '@element-plus/icons-vue'
import MarkdownView from './MarkdownView.vue'
import { setFeedback } from '../api/sessions'

const props = defineProps({
  message: { type: Object, required: true },
})

const isUser = computed(() => props.message.role === 'user')
const isStreaming = computed(() => props.message.streaming)

// ---------- 引用展示：只显示回答中实际引用的来源，不含整段原文 ----------
// 解析回答文本里的 [序号] 标记，仅保留对应编号的来源文档名
const citedIndices = computed(() => {
  const text = props.message.content || ''
  const set = new Set()
  const re = /\[(\d+)\]|［(\d+)］/g
  let m
  while ((m = re.exec(text))) set.add(parseInt(m[1] || m[2], 10))
  return set
})
const visibleCitations = computed(() => {
  if (!props.message.citations?.length) return []
  return props.message.citations
    .map((c, i) => ({ ...c, ref: i + 1 }))
    .filter((c) => citedIndices.value.has(c.ref))
})

// ---------- 反馈（里程碑 7 接入） ----------
const feedbackLoading = ref(false)
async function handleFeedback(type) {
  if (feedbackLoading.value || props.message.feedback === type) return
  feedbackLoading.value = true
  try {
    const res = await setFeedback({ message_id: props.message.id, feedback: type })
    props.message.feedback = res.feedback
    ElMessage.success('感谢反馈')
  } catch (e) {
    /* 错误提示由拦截器处理 */
  } finally {
    feedbackLoading.value = false
  }
}
</script>

<template>
  <div class="msg-row" :class="{ 'is-user': isUser }">
    <div class="msg-avatar">
      <el-avatar :size="34" :class="isUser ? 'avatar-user' : 'avatar-bot'">
        <el-icon v-if="!isUser"><ChatDotRound /></el-icon>
        <el-icon v-else><User /></el-icon>
      </el-avatar>
    </div>

    <div class="msg-body">
      <div class="msg-bubble">
        <!-- 用户消息：纯文本 -->
        <div v-if="isUser" class="msg-text">{{ message.content }}</div>

        <!-- 模型消息：工具调用状态 + Markdown + 流式光标 -->
        <template v-else>
          <div v-if="message.tools?.length" class="tool-list">
            <div v-for="(t, i) in message.tools" :key="i" class="tool-chip">🔧 {{ t }}</div>
          </div>
          <!-- Self-RAG 自省信息：修正过则提示，并列出发现的问题 -->
          <div
            v-if="message.reflection?.revised"
            class="tool-list"
          >
            <el-tag size="small" type="warning" class="tool-chip">
              🔍 Self-RAG 已自省修正（{{ message.reflection.rounds }} 轮）{{
                message.reflection.issues?.length ? `：${message.reflection.issues.join('；')}` : ''
              }}
            </el-tag>
          </div>
          <MarkdownView :content="message.content" />
          <span v-if="isStreaming" class="stream-cursor">▍</span>
        </template>
      </div>

      <!-- 引用来源：仅显示回答中实际引用的文档名，无引用则不显示 -->
      <div v-if="visibleCitations.length" class="citations">
        <div class="citations-title">📚 引用来源</div>
        <div class="citation-list">
          <el-tag
            v-for="cite in visibleCitations"
            :key="cite.ref"
            size="small"
            type="info"
            class="citation-chip"
          >[{{ cite.ref }}] {{ cite.doc_name }}</el-tag>
        </div>
      </div>

      <!-- 元信息：缓存命中 + 延迟 + 反馈 -->
      <div v-if="!isUser && !isStreaming && message.content" class="msg-meta">
        <el-tooltip v-if="message.cached" content="该回答命中语义缓存，未调用大模型" placement="top">
          <el-tag size="small" type="success" class="cache-tag">⚡ 命中缓存</el-tag>
        </el-tooltip>
        <span v-if="message.latency_ms" class="latency">耗时 {{ message.latency_ms }}ms</span>
        <div class="feedback" v-loading="feedbackLoading">
          <el-tooltip content="有帮助" placement="top">
            <el-icon
              class="feedback-icon"
              :class="{ active: message.feedback === 'up' }"
              @click="handleFeedback('up')"
            >👍</el-icon>
          </el-tooltip>
          <el-tooltip content="没帮助" placement="top">
            <el-icon
              class="feedback-icon"
              :class="{ active: message.feedback === 'down' }"
              @click="handleFeedback('down')"
            >👎</el-icon>
          </el-tooltip>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg-row {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
}

.msg-row.is-user {
  flex-direction: row-reverse;
}

.avatar-user {
  background: #2563eb;
  color: #fff;
}

.avatar-bot {
  background: #f59e0b;
  color: #fff;
}

.msg-body {
  max-width: 78%;
  display: flex;
  flex-direction: column;
}

.is-user .msg-body {
  align-items: flex-end;
}

.msg-bubble {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
}

.is-user .msg-bubble {
  background: #2563eb;
  color: #fff;
  border-top-right-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-row:not(.is-user) .msg-bubble {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-top-left-radius: 4px;
  max-width: 100%;
  overflow-wrap: break-word;
}

.msg-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.stream-cursor {
  display: inline-block;
  color: #2563eb;
  animation: blink 1s infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.tool-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.tool-chip {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  background: #f0f7ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
  font-size: 12px;
  line-height: 1.6;
}

.citations {
  margin-top: 10px;
  max-width: 100%;
}

.citations-title {
  font-size: 12px;
  color: #9ca3af;
  margin-bottom: 6px;
}

.citation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.citation-chip {
  border-radius: 6px;
  background: #f8fafc;
  border-color: #e2e8f0;
}

.msg-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 6px;
  font-size: 12px;
  color: #9ca3af;
}

.cache-tag {
  cursor: pointer;
}

.feedback {
  display: flex;
  gap: 10px;
  min-height: 20px;
}

.feedback-icon {
  cursor: pointer;
  font-size: 14px;
  font-style: normal;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.feedback-icon:hover,
.feedback-icon.active {
  opacity: 1;
}
</style>
