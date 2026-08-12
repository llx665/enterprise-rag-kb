import { useAuthStore } from '../stores/auth'

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

/**
 * SSE 流式问答。
 * @param {Function} onTool 工具调用状态回调（Agent 路径，如“正在查询天气”）
 * @param {Function} onStatus Self-RAG 阶段回调（RAG 路径，如“正在核对回答准确性…”）
 * @param {Function} onFinish 兜底回调：流结束 / 出错 / 手动中断时都会触发，
 *                            用于复位发送状态，避免输入框卡死。
 * @returns {AbortController} 用于中断请求
 */
export function streamChat({ sessionId, question, onMeta, onDelta, onTool, onStatus, onDone, onError, onFinish }) {
  const authStore = useAuthStore()
  const controller = new AbortController()

  fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${authStore.accessToken}`,
    },
    body: JSON.stringify({ session_id: sessionId || null, question }),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err.detail || `请求失败（${response.status}）`)
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          // SSE 事件以空行分隔
          const blocks = buffer.split('\n\n')
          buffer = blocks.pop()
          for (const block of blocks) {
            parseEvent(block, { onMeta, onDelta, onTool, onStatus, onDone, onError })
          }
        }
      } finally {
        // 流自然结束（即使未收到 done 事件）也复位状态
        onFinish?.()
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') onError?.(err)
      // 出错或手动中断：同样复位，避免下次发送被卡住
      onFinish?.()
    })

  return controller
}

/** 解析单个 SSE 事件块 */
function parseEvent(block, handlers) {
  const lines = block.split('\n')
  let event = 'message'
  let data = ''
  for (const line of lines) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) data += line.slice(6).trim()
  }
  if (!data) return
  let payload
  try {
    payload = JSON.parse(data)
  } catch (e) {
    return
  }

  switch (event) {
    case 'meta':
      handlers.onMeta?.(payload)
      break
    case 'delta':
      handlers.onDelta?.(payload.content)
      break
    case 'tool':
      handlers.onTool?.(payload)
      break
    case 'status':
      handlers.onStatus?.(payload)
      break
    case 'done':
      handlers.onDone?.(payload)
      break
    case 'error':
      handlers.onError?.(new Error(payload.detail || '生成失败'))
      break
  }
}
