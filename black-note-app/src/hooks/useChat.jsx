import { useState, useRef, useCallback, useEffect } from 'react'
import { chatApi } from '../api'

const STORAGE_KEY = 'rover_chat_history'

export function useChat(userId) {

  const [messages, setMessages] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      return saved.filter(m => !(m.role === 'ai' && !m.content))
    } catch {
      return []
    }
  })

  const [loading, setLoading] = useState(false)

  // 持久化到 localStorage
  useEffect(() => {
    const toSave = messages.filter(m => !(m.role === 'ai' && !m.content))
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave)) } catch {}
  }, [messages])

  const updateLastAI = useCallback((updater) => {
    setMessages(prev => {
      const next = [...prev]
      const last = next[next.length - 1]
      if (last?.role === 'ai') updater(last)
      return next
    })
  }, [])

  const sendMessage = useCallback(async (text) => {
    const question = text?.trim()
    if (!question || loading) return

    setLoading(true)
    setMessages(prev => [
      ...prev,
      { role: 'user', content: question },
      { role: 'ai', content: '', done: false, debugEvents: [] },
    ])

    const sessionId = String(userId || 'guest')

    try {
      const res = await chatApi.chat({ question, session_id: sessionId })
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

          // ★ 先声明 raw，再做所有判断
          const raw = line.slice(5).replace(/^ /, '')
          if (!raw || raw === '[DONE]') continue

          // 调试事件：[DEBUG:type:value]
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

          // 普通 token：还原换行符再追加
          const token = raw.replace(/\\n/g, '\n')
          updateLastAI(msg => { msg.content += token })
        }
      }

      updateLastAI(msg => { msg.done = true })

    } catch (err) {
      console.error('Chat error:', err)
      updateLastAI(msg => {
        msg.content = '请求失败，请稍后再试～'
        msg.done = true
      })
    } finally {
      setLoading(false)
    }
  }, [loading, userId, updateLastAI])

  const clearHistory = useCallback(() => {
    setMessages([])
    localStorage.removeItem(STORAGE_KEY)
  }, [])

  return {
    messages,
    loading,
    sendMessage,
    clearHistory,
    isEmpty: messages.length === 0,
  }
}