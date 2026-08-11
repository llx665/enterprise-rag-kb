import request from './request'

export const listSessions = (params) => request.get('/sessions', { params })
export const createSession = () => request.post('/sessions')
export const getSessionMessages = (id) => request.get(`/sessions/${id}/messages`)
export const renameSession = (id, title) => request.put(`/sessions/${id}`, { title })
export const deleteSession = (id) => request.delete(`/sessions/${id}`)
export const setFeedback = (data) => request.post('/chat/feedback', data)
