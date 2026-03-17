import axios from 'axios'

// 创建axios实例，所有请求走 /api 前缀，由 Vite proxy 转发到后端
const http = axios.create({
  baseURL: '/api',
  timeout: 10000,       
})

// 请求拦截器：自动带上token
http.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) config.headers['Authorization'] = token
  return config
})

// 响应拦截器
http.interceptors.response.use(
  (res) => {
    const data = res.data
    if (data.code === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('userInfo')
      window.location.href = '/'
      return Promise.reject(data)
    }
    if (data.code !== 200) {
      return Promise.reject(data)
    }
    return data
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// ── 用户接口 ──
export const userApi = {
  register: (data) => http.post('/user/register', data),
  login:    (data) => http.post('/user/login', data),
  getById:  (id)   => http.get(`/user/${id}`),
  updateMe: (data) => http.put('/user/me', data),
}

// ── 笔记接口 ──
export const noteApi = {
  publish:      (data)   => http.post('/note/publish', data),
  getById:      (id)     => http.get(`/note/${id}`),
  updateNote:   (id, data) => http.put(`/note/update/${id}`, data), 
  deleteNote:   (id)     => http.delete(`/note/delete/${id}`),
  listByUser:   (userId) => http.get(`/note/list/${userId}`),
  like:         (noteId) => http.post(`/note/like/${noteId}`),
  getLikeCount: (noteId) => http.get(`/note/like/count/${noteId}`),
  isLiked:      (noteId) => http.get(`/note/like/status/${noteId}`), 
  noteList:     (page = 1, size = 20) => http.get(`/note/list?page=${page}&size=${size}`),
}

// ── AI 助手接口 ──
// api.js
export const chatApi = {
  chat: (data, signal) => {   // ← 加 signal 参数
      const token = localStorage.getItem('token')
      return fetch('/api/ai/chat', {
          method: 'POST',
          headers: {
              'Content-Type': 'application/json',
              'Authorization': token,
          },
          body: JSON.stringify(data),
          signal,   // ← 传给 fetch，abort 时自动断开连接
      })
  },
}
// ── 会话接口（单独导出）──
export const sessionApi = {
  list:   ()                 => http.get('/chat/sessions'),
  upsert: (sessionId, title) => http.post(`/chat/sessions/${sessionId}`, { title }),
  delete: (sessionId)        => http.delete(`/chat/sessions/${sessionId}`),
}

// ── 关注接口 ──
export const followApi = {
  follow:       (userId) => http.post(`/follow/${userId}`),
  isFollow:     (userId) => http.get(`/follow/isFollow/${userId}`),
  commonFollow: (userId) => http.get(`/follow/common/${userId}`),
  followList:   (userId) => http.get(`/follow/list/${userId}`),
}

// ── Feed接口 ──
export const feedApi = {
  getFeed: (lastTimestamp = 0, pageSize = 12) => http.get('/feed', { params: { lastTimestamp, pageSize } })
}

// ── 文件上传 ──
export const fileApi = {
  upload: (file) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/file/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  }
}

export default http