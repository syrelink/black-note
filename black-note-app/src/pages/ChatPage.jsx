import { useState, useRef, useEffect, useCallback } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useChat } from '../hooks/useChat'
import styles from './ChatPage.module.css'

marked.setOptions({ breaks: true, gfm: true })

const SUGGESTIONS = [
  '帮我列出最近的笔记',
  '我有关于 Python 的笔记吗？',
  '总结一下我的学习内容',
  '分析一下我最近在关注什么',
]

// 解析工具调用 chip
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

// AI 气泡内容：调试面板 + Markdown 渲染
function AiBubble({ content, done, debugEvents = [] }) {
  const { clean, tools } = parseToolCalls(content)

  // 修复：确保 ## 标题前有换行，marked 才能识别
  const fixed = clean.replace(/([^\n])(#{1,4}\s)/g, '$1\n\n$2')
  const html  = fixed ? DOMPurify.sanitize(marked.parse(fixed)) : ''

  return (
    <div>

      {/* 调试面板 */}
      {debugEvents.length > 0 && (
        <div className={styles.debugPanel}>
          {debugEvents.map((e, i) => (
            <span key={i} className={styles.debugEvent}>
              {e.type === 'llm_call' ? `🧠 LLM #${e.value}` : `🔧 ${e.value}`}
            </span>
          ))}
        </div>
      )}

      {/* 工具调用 chip */}
      {tools.map((t, i) => (
        <div key={i} className={styles.toolChip}>
          <span className={styles.toolDot} />{t}
        </div>
      ))}

      {/* 正文：有内容则渲染 Markdown，否则显示打字动画 */}
      {clean
        ? <div className={styles.mdBody} dangerouslySetInnerHTML={{ __html: html }} />
        : <span className={styles.typing}><span /><span /><span /></span>
      }

      {/* 打字光标：流式进行中且有内容时显示 */}
      {!done && clean && <span className={styles.cursor} />}
    </div>
  )
}

// 欢迎页
function WelcomeScreen({ onSend }) {
  return (
    <div className={styles.welcome}>
      <div className={styles.welcomeAvatar}>R</div>
      <h2 className={styles.welcomeTitle}>Rover</h2>
      <p className={styles.welcomeSub}>你的 AI 笔记助手，帮你搜索、回忆和总结笔记</p>
      <div className={styles.suggestions}>
        {SUGGESTIONS.map(s => (
          <button key={s} className={styles.suggestion} onClick={() => onSend(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}

// 消息列表
function MessageList({ messages, onClear }) {
  const bottomRef    = useRef(null)
  const listRef      = useRef(null)
  const userScrolled = useRef(false)

  const handleScroll = useCallback(() => {
    const el = listRef.current
    if (!el) return
    userScrolled.current = (el.scrollHeight - el.scrollTop - el.clientHeight) > 80
  }, [])

  useEffect(() => {
    if (!userScrolled.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  return (
    <>
      <div className={styles.topBar}>
        <button className={styles.clearBtn} onClick={onClear}>清空对话</button>
      </div>

      <div ref={listRef} className={styles.messages} onScroll={handleScroll}>
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`${styles.row} ${msg.role === 'user' ? styles.userRow : styles.aiRow}`}
          >
            {/* AI 头像 */}
            {msg.role === 'ai' && (
              <div className={styles.aiAvatar}>R</div>
            )}

            {/* ★ 气泡：只渲染一次，修复之前重复渲染的问题 */}
            <div className={`${styles.bubble} ${msg.role === 'user' ? styles.userBubble : styles.aiBubble}`}>
              {msg.role === 'user'
                ? msg.content
                : <AiBubble
                    content={msg.content}
                    done={msg.done}
                    debugEvents={msg.debugEvents || []}
                  />
              }
            </div>
          </div>
        ))}
        <div ref={bottomRef} style={{ height: 8 }} />
      </div>
    </>
  )
}

// 输入框
function InputBar({ loading, onSend }) {
  const [input, setInput] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    if (!loading) inputRef.current?.focus()
  }, [loading])

  const handleSend = () => {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    onSend(q)
  }

  return (
    <div className={styles.inputWrap}>
      <div className={styles.inputBox}>
        <input
          ref={inputRef}
          className={styles.input}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          placeholder="问问 Rover..."
          disabled={loading}
        />
        <button
          type="button"
          className={styles.sendBtn}
          onClick={handleSend}
          disabled={loading || !input.trim()}
        >
          {loading
            ? <span className={styles.sendLoading} />
            : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M22 2L11 13M22 2L15 22 11 13 2 9l20-7z" />
              </svg>
            )
          }
        </button>
      </div>
      <p className={styles.hint}>Rover 可能会出错，重要内容请自行核实</p>
    </div>
  )
}

// 主页面
export default function ChatPage({ userId }) {
  const { messages, loading, sendMessage, clearHistory, isEmpty } = useChat(userId)

  return (
    <div className={styles.page}>
      {isEmpty
        ? <WelcomeScreen onSend={sendMessage} />
        : <MessageList messages={messages} onClear={clearHistory} />
      }
      <InputBar loading={loading} onSend={sendMessage} />
    </div>
  )
}