import request from './request'

export const uploadDocument = (file, description) => {
  const formData = new FormData()
  formData.append('file', file)
  if (description) formData.append('description', description)
  return request.post('/kb/documents', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000, // 大文件上传放宽超时
  })
}

export const listDocuments = (params) => request.get('/kb/documents', { params })
export const getDocument = (id) => request.get(`/kb/documents/${id}`)
export const deleteDocument = (id) => request.delete(`/kb/documents/${id}`)
export const reindexDocument = (id) => request.post(`/kb/documents/${id}/reindex`)
export const getKbStats = () => request.get('/kb/stats')
export const testSearch = (data) => request.post('/kb/search', data)
