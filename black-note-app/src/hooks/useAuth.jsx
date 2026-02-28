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

  const logout = () => {
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
