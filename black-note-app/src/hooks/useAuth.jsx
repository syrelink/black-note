import { useState,  createContext, useContext } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token,    setToken]   = useState(() => localStorage.getItem('token') || '')
  const [userInfo, setUserInfo] = useState(() => {
    const saved = localStorage.getItem('userInfo')
    return saved ? JSON.parse(saved) : null  
  })

  const updateUser = (patch) => {
    setUserInfo(prev => {
      const next = { ...prev, ...patch }
      localStorage.setItem('userInfo', JSON.stringify(next))
      return next
    })
  }

  const login = (tk, info) => { 
    setToken(tk)
    setUserInfo(info)
    localStorage.setItem('token', tk)
    localStorage.setItem('userInfo', JSON.stringify(info))
  }

// useAuth.jsx
const logout = () => {
  // 清除当前用户的所有会话数据
  const uid = userInfo?.id
  if (uid) {
      // 取出所有 session，逐个删除消息
      try {
          const sessions = JSON.parse(
              localStorage.getItem(`rover_sessions_${uid}`) || '[]'
          )
          sessions.forEach(s => {
              localStorage.removeItem(`rover_msgs_${uid}_${s.id}`)
          })
          localStorage.removeItem(`rover_sessions_${uid}`)
      } catch {}
  }

  setToken('')
  setUserInfo(null)
  localStorage.removeItem('token')
  localStorage.removeItem('userInfo')
}

  return (
    <AuthContext.Provider value={{  
      token, userInfo, login, logout, updateUser, isLogin: !!token,
      // 便捷属性
      username:  userInfo?.username  || '',
      nickname:  userInfo?.nickname  || '',
      avatar:    userInfo?.avatar    || null,
      userId:    userInfo?.id        || null,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
