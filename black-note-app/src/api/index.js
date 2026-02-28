import axios from 'axios'

// 创建axios实例，所有请求走 /api 前缀，vite proxy转发到后端
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
  getById:    (id) => http.get(`/note/${id}`),
  updateNote:   (id, data) => http.put(`/note/update/${id}`, data), 
  deleteNote: (id) => http.get(`/note/delete/${id}`),
  listByUser:   (userId) => http.get(`/note/list/${userId}`),
  like:         (noteId) => http.post(`/note/like/${noteId}`),
  getLikeCount: (noteId) => http.get(`/note/like/count/${noteId}`),
  isLiked:      (noteId) => http.get(`/note/like/status/${noteId}`), 
  noteList: (page = 1, size = 20) => http.get(`/note/list?page=${page}&size=${size}`),
}

// ── 关注接口 ──
export const followApi = {
  follow:       (userId) => http.post(`/follow/${userId}`),
  isFollow:     (userId) => http.get(`/follow/isFollow/${userId}`),
  commonFollow: (userId) => http.get(`/follow/common/${userId}`),
  followList: (userId) => http.get(`/follow/list/${userId}`),
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
