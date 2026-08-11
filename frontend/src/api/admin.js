import request from './request'

/** 数据看板聚合统计 */
export function getDashboard() {
  return request.get('/admin/dashboard')
}

/** 答案反馈列表 */
export function getFeedback({ page = 1, page_size = 20 } = {}) {
  return request.get('/admin/feedback', { params: { page, page_size } })
}
