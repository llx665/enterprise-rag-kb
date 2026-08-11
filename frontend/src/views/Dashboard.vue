<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
// 按需引入 echarts，避免整包（1MB+）拖慢首屏
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import {
  Odometer,
  ChatDotRound,
  Connection,
  Timer,
  Lightning,
  DataLine,
} from '@element-plus/icons-vue'
import { getDashboard, getFeedback } from '../api/admin'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

// ---------------- 数据 ----------------
const stats = ref(null)
const trends = ref({ dates: [], questions: [], avg_latency_ms: [], new_users: [] })
const feedbackList = ref([])
const feedbackTotal = ref(0)
const feedbackPage = ref(1)
const feedbackLoading = ref(false)
const loading = ref(true)

const chartRef = ref(null)
const latencyChartRef = ref(null)
let chart = null
let latencyChart = null

async function loadDashboard() {
  loading.value = true
  try {
    const data = await getDashboard()
    stats.value = data.stats
    trends.value = data.trends
    buildCards()
    await nextTick()
    renderCharts()
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

async function loadFeedback() {
  feedbackLoading.value = true
  try {
    const data = await getFeedback({ page: feedbackPage.value, page_size: 10 })
    feedbackList.value = data.items
    feedbackTotal.value = data.total
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    feedbackLoading.value = false
  }
}

// ---------------- 图表（ECharts，遵循品牌调色：单序列 1 个 hue） ----------------
function renderCharts() {
  if (!chartRef.value || !latencyChartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  if (!latencyChart) latencyChart = echarts.init(latencyChartRef.value)

  // 7 天问答量（单序列折线+面积，蓝色）
  const questionOpt = {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    xAxis: {
      type: 'category',
      data: trends.value.dates,
      axisLine: { lineStyle: { color: '#c3c2b7' } },
      axisLabel: { color: '#898781', fontSize: 12 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#e1e0d9' } },
      axisLabel: { color: '#898781' },
    },
    series: [
      {
        type: 'line',
        data: trends.value.questions,
        name: '每日问答量',
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2, color: '#2a78d6' },
        itemStyle: { color: '#2a78d6' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(42,120,214,0.25)' },
              { offset: 1, color: 'rgba(42,120,214,0.02)' },
            ],
          },
        },
      },
    ],
  }

  // 7 天平均生成延迟（单序列折线，橙色）
  const latencyOpt = {
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 16, top: 24, bottom: 28 },
    xAxis: {
      type: 'category',
      data: trends.value.dates,
      axisLine: { lineStyle: { color: '#c3c2b7' } },
      axisLabel: { color: '#898781', fontSize: 12 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#898781', formatter: '{value}ms' },
      splitLine: { lineStyle: { color: '#e1e0d9' } },
    },
    series: [
      {
        type: 'line',
        data: trends.value.avg_latency_ms,
        name: '平均生成延迟',
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2, color: '#eb6834' },
        itemStyle: { color: '#eb6834' },
      },
    ],
  }

  chart.setOption(questionOpt, true)
  latencyChart.setOption(latencyOpt, true)
}

// 窗口缩放自适应
function onResize() {
  chart?.resize()
  latencyChart?.resize()
}

// ---------------- 统计卡片 ----------------
const cards = ref([])
function buildCards() {
  if (!stats.value) return
  cards.value = [
    { label: '注册用户', value: stats.value.total_users, icon: Odometer },
    { label: '会话总数', value: stats.value.total_sessions, icon: ChatDotRound },
    { label: '问答次数', value: stats.value.total_questions, icon: DataLine },
    { label: '平均生成延迟', value: `${stats.value.avg_latency_ms}ms`, icon: Timer },
    { label: '缓存命中率', value: `${(stats.value.cache_hit_rate * 100).toFixed(1)}%`, icon: Lightning },
    {
      label: '用户好评率',
      value: `${(stats.value.satisfaction_rate * 100).toFixed(1)}%`,
      icon: Connection,
      sub: `👍 ${stats.value.good_feedback} · 👎 ${stats.value.bad_feedback}`,
    },
  ]
}

onMounted(() => {
  loadDashboard()
  loadFeedback()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  latencyChart?.dispose()
})

// 反馈表格
function formatTime(iso) {
  return iso ? iso.replace('T', ' ').slice(0, 19) : ''
}
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <!-- KPI 统计卡片 -->
    <div class="kpi-row">
      <div v-for="(card, i) in cards" :key="i" class="kpi-card">
        <div class="kpi-icon">
          <el-icon :size="22"><component :is="card.icon" /></el-icon>
        </div>
        <div class="kpi-body">
          <div class="kpi-value">{{ card.value }}</div>
          <div class="kpi-label">{{ card.label }}</div>
          <div v-if="card.sub" class="kpi-sub">{{ card.sub }}</div>
        </div>
      </div>
    </div>

    <!-- 趋势图 -->
    <div class="chart-row">
      <div class="chart-card">
        <div class="chart-title">📈 近 7 天问答量趋势</div>
        <div ref="chartRef" class="chart-box"></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">⏱️ 近 7 天平均生成延迟</div>
        <div ref="latencyChartRef" class="chart-box"></div>
      </div>
    </div>

    <!-- 反馈明细 -->
    <div class="feedback-card">
      <div class="chart-title">💬 用户反馈明细（RAG 效果评估）</div>
      <el-table :data="feedbackList" v-loading="feedbackLoading" stripe style="width: 100%">
        <el-table-column prop="username" label="用户" width="110" />
        <el-table-column label="反馈" width="90">
          <template #default="{ row }">
            <el-tag :type="row.feedback === 'up' ? 'success' : 'danger'" size="small">
              {{ row.feedback === 'up' ? '👍 有帮助' : '👎 没帮助' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question" label="问题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="answer" label="回答摘要" min-width="260" show-overflow-tooltip />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          background
          layout="prev, pager, next, total"
          :total="feedbackTotal"
          :page-size="10"
          :current-page="feedbackPage"
          @current-change="(p) => { feedbackPage = p; loadFeedback() }"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.kpi-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
}

.kpi-icon {
  width: 46px;
  height: 46px;
  border-radius: 10px;
  background: #eff6ff;
  color: #2563eb;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.kpi-value {
  font-size: 22px;
  font-weight: 700;
  color: #111827;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.kpi-label {
  font-size: 12px;
  color: #6b7280;
  margin-top: 2px;
}

.kpi-sub {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 2px;
}

.chart-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

@media (max-width: 1000px) {
  .chart-row {
    grid-template-columns: 1fr;
  }
}

.chart-card,
.feedback-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px;
}

.chart-title {
  font-size: 14px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 10px;
}

.chart-box {
  height: 240px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
