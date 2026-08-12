<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled, Search, Document, Refresh } from '@element-plus/icons-vue'
import {
  deleteDocument,
  getDocument,
  getKbStats,
  listDocuments,
  reindexDocument,
  testSearch,
  uploadDocument,
} from '../api/kb'

// ---------- 数据 ----------
const stats = ref({ total_documents: 0, ready_documents: 0, total_chunks: 0, vector_points: 0 })
const documents = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const statusFilter = ref('')
const loading = ref(false)
const uploading = ref(false)

// 状态映射
const statusMap = {
  pending: { label: '待处理', type: 'info' },
  processing: { label: '处理中', type: 'warning' },
  ready: { label: '已就绪', type: 'success' },
  failed: { label: '处理失败', type: 'danger' },
}

const hasProcessing = computed(() =>
  documents.value.some((d) => d.status === 'pending' || d.status === 'processing')
)

function formatSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function loadStats() {
  stats.value = await getKbStats()
}

async function loadDocuments() {
  loading.value = true
  try {
    const data = await listDocuments({
      page: page.value,
      page_size: pageSize.value,
      status: statusFilter.value || undefined,
    })
    documents.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function refreshAll() {
  loadDocuments()
  loadStats()
}

// ---------- 轮询：有文档处理中时定时刷新 ----------
let timer = null
function startPolling() {
  stopPolling()
  timer = setInterval(() => {
    loadDocuments()
    loadStats()
    if (!hasProcessing.value) stopPolling()
  }, 3000)
}
function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

// ---------- 上传 ----------
const uploadRef = ref()
async function handleUpload(options) {
  uploading.value = true
  try {
    await uploadDocument(options.file, '')
    ElMessage.success('上传成功，开始后台处理')
    loadDocuments()
    loadStats()
    startPolling()
  } catch (e) {
    // 错误提示已在拦截器统一处理
  } finally {
    uploading.value = false
    if (options.onSuccess) options.onSuccess({})
  }
}

// ---------- 删除 ----------
async function handleDelete(row) {
  await ElMessageBox.confirm(
    `确定删除文档「${row.filename}」吗？其向量数据将一并清除。`,
    '删除确认',
    { type: 'warning' }
  )
  await deleteDocument(row.id)
  ElMessage.success('已删除')
  loadDocuments()
  loadStats()
}

// ---------- 重新处理 ----------
async function handleReindex(row) {
  await ElMessageBox.confirm(`确定重新处理「${row.filename}」吗？`, '重新处理', { type: 'info' })
  await reindexDocument(row.id)
  ElMessage.success('已开始重新处理')
  loadDocuments()
  startPolling()
}

// ---------- 查看分块 ----------
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailDoc = ref(null)
async function handleViewDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detailDoc.value = null
  try {
    detailDoc.value = await getDocument(row.id)
  } finally {
    detailLoading.value = false
  }
}

// ---------- 检索测试 ----------
const searchVisible = ref(false)
const searchForm = ref({ query: '', top_k: 5 })
const searchLoading = ref(false)
const searchResults = ref([])
async function handleTestSearch() {
  if (!searchForm.value.query.trim()) {
    ElMessage.warning('请输入检索内容')
    return
  }
  searchLoading.value = true
  try {
    searchResults.value = await testSearch(searchForm.value)
  } finally {
    searchLoading.value = false
  }
}

onMounted(() => {
  loadDocuments()
  loadStats()
  if (hasProcessing.value) startPolling()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="kb-page">
    <!-- 统计卡片 -->
    <div class="stat-row">
      <el-card shadow="never" class="stat-card">
        <div class="stat-value">{{ stats.total_documents }}</div>
        <div class="stat-label">文档总数</div>
      </el-card>
      <el-card shadow="never" class="stat-card">
        <div class="stat-value" style="color: #67c23a">{{ stats.ready_documents }}</div>
        <div class="stat-label">已就绪文档</div>
      </el-card>
      <el-card shadow="never" class="stat-card">
        <div class="stat-value" style="color: #409eff">{{ stats.total_chunks }}</div>
        <div class="stat-label">分块总数</div>
      </el-card>
      <el-card shadow="never" class="stat-card">
        <div class="stat-value" style="color: #e6a23c">{{ stats.vector_points }}</div>
        <div class="stat-label">向量数据</div>
      </el-card>
    </div>

    <!-- 工具栏 -->
    <el-card shadow="never" class="toolbar">
      <div class="toolbar-left">
        <el-upload
          :show-file-list="false"
          :http-request="handleUpload"
          :disabled="uploading"
          accept=".pdf,.docx,.xlsx,.txt,.md,.py,.js,.ts,.tsx,.jsx,.java,.go,.cpp,.c,.h,.hpp,.cs,.rs,.rb,.php,.swift,.kt"
        >
          <el-button type="primary" :loading="uploading" :icon="UploadFilled">
            上传文档
          </el-button>
          <template #tip>
            <div class="el-upload__tip">支持 PDF / Word / Excel / TXT / Markdown / 常见代码文件，单文件 ≤ 50MB</div>
          </template>
        </el-upload>
        <el-select
          v-model="statusFilter"
          placeholder="状态筛选"
          clearable
          style="width: 140px; margin-left: 16px"
          @change="page = 1; loadDocuments()"
        >
          <el-option label="待处理" value="pending" />
          <el-option label="处理中" value="processing" />
          <el-option label="已就绪" value="ready" />
          <el-option label="处理失败" value="failed" />
        </el-select>
      </div>
      <div class="toolbar-right">
        <el-button :icon="Search" @click="searchVisible = true">检索测试</el-button>
        <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
      </div>
    </el-card>

    <!-- 文档列表 -->
    <el-card shadow="never">
      <el-table :data="documents" v-loading="loading" empty-text="知识库暂无文档">
        <el-table-column prop="filename" label="文件名" min-width="240" show-overflow-tooltip />
        <el-table-column prop="file_type" label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" type="info">.{{ row.file_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusMap[row.status]?.type" size="small">
              {{ statusMap[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="分块数" width="90" align="center" />
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">
            {{ new Date(row.created_at).toLocaleString() }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="Document" @click="handleViewDetail(row)">
              分块
            </el-button>
            <el-button
              link
              type="warning"
              :icon="Refresh"
              :disabled="row.status === 'pending' || row.status === 'processing'"
              @click="handleReindex(row)"
            >
              重处理
            </el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        layout="total, sizes, prev, pager, next"
        :page-sizes="[10, 20, 50]"
        class="pagination"
        @change="loadDocuments"
      />
    </el-card>

    <!-- 分块详情抽屉 -->
    <el-drawer v-model="detailVisible" title="文档分块详情" size="520px">
      <div v-loading="detailLoading">
        <template v-if="detailDoc">
          <el-alert
            :title="`${detailDoc.filename}（共 ${detailDoc.chunks?.length || 0} 个分块）`"
            type="success"
            :closable="false"
            class="drawer-alert"
          />
          <div v-for="(chunk, i) in detailDoc.chunks" :key="chunk.id" class="chunk-item">
            <div class="chunk-index">#{{ i + 1 }} <span class="chunk-token">约 {{ chunk.token_count }} 字符</span></div>
            <div class="chunk-content">{{ chunk.content }}</div>
          </div>
        </template>
      </div>
    </el-drawer>

    <!-- 检索测试对话框 -->
    <el-dialog v-model="searchVisible" title="检索测试（预览命中片段）" width="600px">
      <div class="search-form">
        <el-input
          v-model="searchForm.query"
          placeholder="输入一个问题，查看会命中哪些知识库片段"
          @keyup.enter="handleTestSearch"
        />
        <el-input-number v-model="searchForm.top_k" :min="1" :max="20" />
      </div>
      <el-button type="primary" :loading="searchLoading" @click="handleTestSearch" class="search-btn">
        检索
      </el-button>

      <div v-if="searchResults.length" class="search-results">
        <div v-for="(hit, i) in searchResults" :key="i" class="hit-item">
          <div class="hit-head">
            <span class="hit-score">相关度 {{ hit.score }}</span>
            <span class="hit-doc">{{ hit.doc_name }}（第 {{ hit.chunk_index + 1 }} 块）</span>
          </div>
          <div class="hit-content">{{ hit.content }}</div>
        </div>
      </div>
      <el-empty v-else-if="!searchLoading" description="输入内容后点击检索" />
    </el-dialog>
  </div>
</template>

<style scoped>
.kb-page {
  padding: 20px;
  height: 100%;
  overflow-y: auto;
}

.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.stat-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 18px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #1f2937;
}

.stat-label {
  font-size: 13px;
  color: #9ca3af;
  margin-top: 4px;
}

.toolbar {
  margin-bottom: 16px;
}

.toolbar :deep(.el-card__body) {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.toolbar-left {
  display: flex;
  align-items: flex-start;
}

.toolbar-right {
  display: flex;
  gap: 8px;
}

.pagination {
  margin-top: 16px;
  justify-content: flex-end;
}

.drawer-alert {
  margin-bottom: 16px;
}

.chunk-item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
  background: #fafafa;
}

.chunk-index {
  font-weight: 600;
  font-size: 13px;
  color: #374151;
  margin-bottom: 6px;
}

.chunk-token {
  font-weight: 400;
  color: #9ca3af;
  font-size: 12px;
}

.chunk-content {
  font-size: 13px;
  color: #4b5563;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.search-form {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.search-btn {
  margin-bottom: 16px;
}

.search-results {
  max-height: 400px;
  overflow-y: auto;
}

.hit-item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
  background: #fafafa;
}

.hit-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 12px;
}

.hit-score {
  color: #e6a23c;
  font-weight: 600;
}

.hit-doc {
  color: #9ca3af;
}

.hit-content {
  font-size: 13px;
  color: #4b5563;
  line-height: 1.6;
  white-space: pre-wrap;
}
</style>
