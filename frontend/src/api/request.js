import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import router from '../router'

/**
 * 统一 Axios 实例。
 * - 自动携带 JWT access token
 * - 401 时自动用 refresh token 续期重试
 * - 统一错误提示
 * - 响应直接返回 data（解包）
 */
const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
  timeout: 120000,
})

// 请求拦截：附加 Bearer Token
request.interceptors.request.use((config) => {
  const authStore = useAuthStore()
  if (authStore.accessToken) {
    config.headers.Authorization = `Bearer ${authStore.accessToken}`
  }
  return config
})

// 响应拦截：解包 + 401 自动续期
request.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const { response, config } = error
    if (response && response.status === 401 && !config._retry) {
      config._retry = true
      const authStore = useAuthStore()
      if (authStore.refreshToken) {
        try {
          await authStore.refresh()
          config.headers.Authorization = `Bearer ${authStore.accessToken}`
          return request(config)
        } catch (e) {
          // 刷新失败：强制退出
          authStore.logout()
          router.push('/login')
        }
      }
    }
    const message = response?.data?.detail || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  }
)

export default request
