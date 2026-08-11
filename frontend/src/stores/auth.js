import { defineStore } from 'pinia'
import {
  login as loginApi,
  register as registerApi,
  refreshToken as refreshApi,
  getMe,
} from '../api/auth'

const ACCESS_KEY = 'rag_access_token'
const REFRESH_KEY = 'rag_refresh_token'
const USER_KEY = 'rag_user'

/**
 * 认证状态管理：令牌与用户信息持久化到 localStorage，
 * 保证刷新页面后登录状态不丢失。
 */
export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: localStorage.getItem(ACCESS_KEY) || '',
    refreshToken: localStorage.getItem(REFRESH_KEY) || '',
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
  }),

  getters: {
    isLoggedIn: (state) => !!state.accessToken,
    isAdmin: (state) => state.user?.role === 'admin',
  },

  actions: {
    async login(username, password) {
      const data = await loginApi({ username, password })
      this._setSession(data)
    },

    async register(username, password, nickname) {
      await registerApi({ username, password, nickname })
    },

    async refresh() {
      const data = await refreshApi({ refresh_token: this.refreshToken })
      this._setSession(data)
    },

    async fetchMe() {
      const user = await getMe()
      this.user = user
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    },

    _setSession(data) {
      this.accessToken = data.access_token
      this.refreshToken = data.refresh_token
      this.user = data.user
      localStorage.setItem(ACCESS_KEY, this.accessToken)
      localStorage.setItem(REFRESH_KEY, this.refreshToken)
      localStorage.setItem(USER_KEY, JSON.stringify(this.user))
    },

    logout() {
      this.accessToken = ''
      this.refreshToken = ''
      this.user = null
      localStorage.removeItem(ACCESS_KEY)
      localStorage.removeItem(REFRESH_KEY)
      localStorage.removeItem(USER_KEY)
    },
  },
})
