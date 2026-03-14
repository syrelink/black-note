import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { chatApi } from '../api'
import styles from './ChatPage.module.css'

const SUGGESTIONS = [
  '帮我列出所有笔记标题',
  '我有关于 Python 的笔记吗？',
  '总结一下我的学习内容',
  '最近写了什么？',
]

const STORAGE_KEY = 'rover_chat_history'

// 过滤工具调用标记，返回 { clean, tools }
function parseToolCalls(text) {
  const tools = []
  const clean = text
    .replace(/\[正在调用工具[:：]\s*([^\]]+)\]/g, (_, name) => {
      tools.push(name.trim())
      return ''
    })
    .trim()
  return { clean, tools }
}

// AI 气泡：渲染工具 chip + Markdown 正文
function AiBubbleContent({ content }) {
  const { clean, tools } = parseToolCalls(content)
  return (
    <div>
      {tools.map((t, i) => (
        <div key={i} className={styles.toolChip}>
          <span className={styles.toolDot} />
          {t}
        </div>
      ))}
      {clean && (
        <div className={styles.mdBody}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {clean}
          </ReactMarkdown>
        </div>
      )}
    </div>
  )
}

export default function RoverPage({ userId }) {
  // ★ 修复3：从 localStorage 恢复历史，只保留已完成的消息（过滤掉空 ai 占位）
  const [messages, setMessages] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        const parsed = JSON.parse(saved)
        // 过滤掉 content 为空的 ai 消息（上次异常中断的占位）
        return parsed.filter(m => !(m.role === 'ai' && !m.content))
      }
    } catch {}
    return []
  })
  const [input,   setInput]   = useState('')
  const [loading, setLoading] = useState(false)

  const bottomRef   = useRef(null)
  const inputRef    = useRef(null)
  const messagesRef = useRef(null)   // ★ 修复2：消息容器 ref
  const userScrolled = useRef(false) // ★ 修复2：用户是否主动向上滚动

  // ★ 修复3：消息变化时持久化到 localStorage（只保存已完成的）
  useEffect(() => {
    const toSave = messages.filter(m => !(m.role === 'ai' && !m.content))
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave))
    } catch {}
  }, [messages])

  // ★ 修复2：只有用户没有向上滚动时才自动滚到底部
  useEffect(() => {
    if (!userScrolled.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  // ★ 修复2：监听用户手动滚动
  const handleScroll = useCallback(() => {
    const el = messagesRef.current
    if (!el) return
    // 距离底部超过 80px 认为用户主动向上翻
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    userScrolled.current = distFromBottom > 80
  }, [])

  const sendMessage = async (text) => {
    const question = (text || input).trim()
    if (!question || loading) return

    setInput('')
    setLoading(true)
    userScrolled.current = false  // 发新消息时重置，自动滚到底

    setMessages(prev => [
      ...prev,
      { role: 'user', content: question },
      { role: 'ai',   content: '' },
    ])

    try {
      const res     = await chatApi.chat({ question, session_id: String(userId) })
      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const content = line.slice(5).trim()
          if (!content || content === '[DONE]') continue
          setMessages(prev => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last?.role === 'ai') last.content += content
            return [...updated]
          })
        }
      }
    } catch {
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1].content = '请求失败，请稍后再试～'
        return [...updated]
      })
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  // 清空历史
  const clearHistory = () => {
    setMessages([])
    localStorage.removeItem(STORAGE_KEY)
  }

  const isEmpty = messages.length === 0

  return (
    <div className={styles.page}>

      {isEmpty && (
        <div className={styles.welcome}>
          <div className={styles.welcomeAvatar}>R</div>
          <h2 className={styles.welcomeTitle}>Rover</h2>
          <p className={styles.welcomeSub}>你的 AI 笔记助手，帮你搜索、回忆和总结笔记</p>
          <div className={styles.suggestions}>
            {SUGGESTIONS.map(s => (
              <button key={s} className={styles.suggestion} onClick={() => sendMessage(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {!isEmpty && (
        <>
          {/* 顶部清空按钮 */}
          <div className={styles.topBar}>
            <button className={styles.clearBtn} onClick={clearHistory}>清空对话</button>
          </div>

          {/* ★ 修复2：消息容器绑定 ref + onScroll */}
          <div
            ref={messagesRef}
            className={styles.messages}
            onScroll={handleScroll}
          >
            {messages.map((msg, i) => (
              <div key={i} className={`${styles.row} ${msg.role === 'user' ? styles.userRow : styles.aiRow}`}>
                {msg.role === 'ai' && <div className={styles.aiAvatar}>R</div>}
                <div className={`${styles.bubble} ${msg.role === 'user' ? styles.userBubble : styles.aiBubble}`}>
                  {msg.role === 'user' ? (
                    msg.content
                  ) : msg.content ? (
                    // ★ 修复1：AI 回复用 ReactMarkdown 渲染
                    <AiBubbleContent content={msg.content} />
                  ) : (
                    <span className={styles.typing}><span /><span /><span /></span>
                  )}
                </div>
              </div>
            ))}
            <div ref={bottomRef} style={{ height: 8 }} />
          </div>
        </>
      )}

      <div className={styles.inputWrap}>
        <div className={styles.inputBox}>
          <input
            ref={inputRef}
            className={styles.input}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
            }}
            placeholder="问问 Rover..."
            disabled={loading}
          />
          <button
            type="button"
            className={styles.sendBtn}
            onClick={() => sendMessage()}
            disabled={loading || !input.trim()}
          >
            {loading
              ? <span className={styles.sendLoading} />
              : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M22 2L11 13M22 2L15 22 11 13 2 9l20-7z" />
                </svg>
            }
          </button>
        </div>
        <p className={styles.hint}>Rover 可能会出错，重要内容请自行核实</p>
      </div>
    </div>
  )
}