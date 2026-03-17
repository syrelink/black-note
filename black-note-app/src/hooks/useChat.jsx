import { useState, useCallback, useEffect, useRef } from 'react'
import { chatApi, sessionApi } from '../api'   // ← 加 sessionApi

const messagesKey = (uid, sid) => `rover_msgs_${uid}_${sid}`

function createSession() {
  return {
    id:        crypto.randomUUID(),
    title:     '新对话',
    createdAt: Date.now(),
  }
}

function extractTitle(messages) {
  const first = messages.find(m => m.role === 'user')
  if (!first) return '新对话'
  return first.content.slice(0, 20) + (first.content.length > 20 ? '…' : '')
}

export function formatDate(ts) {
  const d      = new Date(ts)
  const now    = new Date()
  const diffMs = new Date(now.getFullYear(), now.getMonth(), now.getDate())
               - new Date(d.getFullYear(), d.getMonth(), d.getDate())
  if (diffMs === 0)        return '今天'
  if (diffMs === 86400000) return '昨天'
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

export function useChat(userId) {
  const uid = String(userId || 'guest')

  const abortRef = useRef(null)

  const [sessions, setSessions] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [loading,  setLoading]  = useState(false)

  // ── userId 变化时从后端加载会话列表 ─────────────────────
  useEffect(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    setLoading(false)

    // 未登录时清空
    if (!userId) {
      setSessions([])
      setActiveId(null)
      setMessages([])
      return
    }

    // 从后端拉取会话列表
    sessionApi.list()
      .then(res => {
        const saved = res.data || []

        if (saved.length > 0) {
          // 把后端返回的时间格式统一成时间戳
          const formatted = saved.map(s => ({
            id:        s.id,
            title:     s.title,
            createdAt: new Date(s.createdAt).getTime(),
          }))
          setSessions(formatted)
          setActiveId(formatted[0].id)

          // 消息从 localStorage 取（本地缓存）
          try {
            const msgs = JSON.parse(
              localStorage.getItem(messagesKey(uid, formatted[0].id)) || '[]'
            )
            setMessages(msgs.filter(m => !(m.role === 'ai' && !m.content)))
          } catch { setMessages([]) }

        } else {
          // 后端没有历史，创建第一个新 session（先只放前端，发消息后同步后端）
          const s = createSession()
          setSessions([s])
          setActiveId(s.id)
          setMessages([])
        }
      })
      .catch(() => {
        // 请求失败降级到 localStorage
        const s = createSession()
        setSessions([s])
        setActiveId(s.id)
        setMessages([])
      })
  }, [uid])

  // ── 持久化消息到 localStorage（本地缓存，加速加载）────
  useEffect(() => {
    if (!activeId) return
    const toSave = messages.filter(m => !(m.role === 'ai' && !m.content))
    localStorage.setItem(messagesKey(uid, activeId), JSON.stringify(toSave))
  }, [messages, activeId, uid])

  // ── 更新最后一条 AI 消息 ─────────────────────────────────
  const updateLastAI = useCallback((updater) => {
    setMessages(prev => {
      const next = [...prev]
      const last = next[next.length - 1]
      if (last?.role === 'ai') updater(last)
      return next
    })
  }, [])

  // ── 切换 session ─────────────────────────────────────────
  const switchSession = useCallback((sid) => {
    if (sid === activeId) return
    setActiveId(sid)
    try {
      const saved = JSON.parse(localStorage.getItem(messagesKey(uid, sid)) || '[]')
      setMessages(saved.filter(m => !(m.role === 'ai' && !m.content)))
    } catch { setMessages([]) }
  }, [activeId, uid])

  // ── 新建 session ─────────────────────────────────────────
  const newSession = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    const s = createSession()
    setSessions(prev => [s, ...prev])
    setActiveId(s.id)
    setMessages([])
    setLoading(false)
    // 注意：新 session 不立刻同步后端，等发第一条消息时再同步
  }, [])

  // ── 删除 session ─────────────────────────────────────────
  const deleteSession = useCallback((sid, e) => {
    e?.stopPropagation()

    if (sid === activeId && abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setLoading(false)
    }

    // 同步删除后端（fire and forget，不等结果）
    sessionApi.delete(sid).catch(() => {})
    // 清除本地消息缓存
    localStorage.removeItem(messagesKey(uid, sid))

    setSessions(prev => {
      const next = prev.filter(s => s.id !== sid)
      if (next.length === 0) {
        const fresh = createSession()
        setActiveId(fresh.id)
        setMessages([])
        return [fresh]
      }
      if (sid === activeId) {
        setActiveId(next[0].id)
        try {
          const saved = JSON.parse(
            localStorage.getItem(messagesKey(uid, next[0].id)) || '[]'
          )
          setMessages(saved)
        } catch { setMessages([]) }
      }
      return next
    })
  }, [uid, activeId])

  // ── 清空当前会话消息 ─────────────────────────────────────
  const clearHistory = useCallback(() => {
    setMessages([])
    localStorage.removeItem(messagesKey(uid, activeId))
    // 更新后端标题重置为"新对话"
    sessionApi.upsert(activeId, '新对话').catch(() => {})
    setSessions(prev => prev.map(s =>
      s.id === activeId ? { ...s, title: '新对话' } : s
    ))
  }, [uid, activeId])

  // ── 发送消息 ─────────────────────────────────────────────
  const sendMessage = useCallback(async (text) => {
    const question = text?.trim()
    if (!question || loading) return

    const controller = new AbortController()
    abortRef.current = controller

    const isFirstMessage = messages.length === 0

    setLoading(true)
    setMessages(prev => [
      ...prev,
      { role: 'user', content: question },
      { role: 'ai', content: '', done: false, debugEvents: [] },
    ])

    // 第一条消息时同步 session 到后端
    if (isFirstMessage) {
      const title = question.slice(0, 20) + (question.length > 20 ? '…' : '')
      sessionApi.upsert(activeId, title).catch(() => {})
      setSessions(prev => prev.map(s =>
        s.id === activeId ? { ...s, title } : s
      ))
    }

    try {
      const res = await chatApi.chat(
        { question, session_id: activeId },
        controller.signal
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const raw = line.slice(5).replace(/^ /, '')
          if (!raw || raw === '[DONE]') continue

          if (raw.startsWith('[DEBUG:')) {
            const match = raw.match(/\[DEBUG:(\w+):(.+)\]/)
            if (match) {
              const [, type, value] = match
              updateLastAI(msg => {
                if (!msg.debugEvents) msg.debugEvents = []
                msg.debugEvents.push({ type, value, time: Date.now() })
              })
            }
            continue
          }

          const token = raw.replace(/\\n/g, '\n')
          updateLastAI(msg => { msg.content += token })
        }
      }

      updateLastAI(msg => { msg.done = true })

    } catch (err) {
      if (err.name === 'AbortError') {
        updateLastAI(msg => { msg.done = true; msg.aborted = true })
        return
      }
      console.error('Chat error:', err)
      updateLastAI(msg => {
        msg.content = '请求失败，请稍后再试～'
        msg.done = true
      })
    } finally {
      setLoading(false)
      abortRef.current = null
    }
  }, [loading, activeId, messages, updateLastAI])

  // ── 手动终止当前输出 ─────────────────────────────────────
  const abortCurrent = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
  }, [])

  return {
    sessions,
    activeId,
    messages,
    loading,
    sendMessage,
    clearHistory,
    newSession,
    deleteSession,
    switchSession,
    abortCurrent,
    isEmpty: messages.length === 0,
  }
}
