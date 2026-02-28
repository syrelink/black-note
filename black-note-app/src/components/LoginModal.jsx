import { useState } from 'react'
import { userApi } from '../api'
import { useAuth } from '../hooks/useAuth'
import styles from './LoginModal.module.css'

export default function LoginModal({ onClose }) {
  const { login } = useAuth()
  const [mode,     setMode]     = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [msg,      setMsg]      = useState('')
  const [loading,  setLoading]  = useState(false)

  const handleSubmit = async () => {
    if (!username.trim() || !password.trim()) {
      setMsg('请填写用户名和密码'); return
    }
    setLoading(true); setMsg('')
    try {
      if (mode === 'register') {
        await userApi.register({ username, password })
        setMsg('注册成功，请登录')
        setTimeout(() => { setMode('login'); setMsg('') }, 1500)
      } else {
        const res = await userApi.login({ username, password })
        // res.data = { token, id, username, nickname, avatar }
        const { token, ...userInfo } = res.data
        login(token, userInfo)   // 存入 Context + localStorage
        setMsg('登录成功')
        setTimeout(onClose, 800)
      }
    } catch (e) {
      setMsg(
        // 情况1：拦截器里 Promise.reject(res.data) 得到的 e.message
        e.message
        // 情况2：axios Error 对象里，后端返回的 Result.message
        || e.response?.data?.message
        // 兜底
        || '系统繁忙'
      )
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e) => e.key === 'Enter' && handleSubmit()

  return (
    <div className={styles.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>
        <div className={styles.brand}>小黑<span>书</span></div>
        <p className={styles.sub}>记录生活，分享美好</p>

        <div className={styles.toggle}>
          <button
            className={`${styles.toggleBtn} ${mode === 'login' ? styles.active : ''}`}
            onClick={() => { setMode('login'); setMsg('') }}
          >登录</button>
          <button
            className={`${styles.toggleBtn} ${mode === 'register' ? styles.active : ''}`}
            onClick={() => { setMode('register'); setMsg('') }}
          >注册</button>
        </div>

        <div className={styles.field}>
          <label htmlFor="username">用户名</label>
          <input
            id="username" name="username" type="text"
            autoComplete="username"
            placeholder="请输入用户名"
            value={username}
            onChange={e => setUsername(e.target.value)}
            onKeyDown={handleKey}
          />
        </div>
        <div className={styles.field}>
          <label htmlFor="password">密码</label>
          <input
            id="password" name="password" type="password"
            autoComplete="current-password"
            placeholder="请输入密码"
            value={password}
            onChange={e => setPassword(e.target.value)}
            onKeyDown={handleKey}
          />
        </div>

        {msg && <div className={styles.msg}>{msg}</div>}

        <button
          className={styles.submitBtn}
          onClick={handleSubmit}
          disabled={loading}
        >
          {loading ? '处理中...' : mode === 'login' ? '登录' : '注册'}
        </button>
      </div>
    </div>
  )
}