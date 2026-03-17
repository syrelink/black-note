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

// ── AI 气泡 ───────────────────────────────────────────────────
function AiBubble({ content, done, debugEvents = [], aborted = false }) {
  const { clean, tools } = parseToolCalls(content)
  const fixed = clean.replace(/([^\n])(#{1,4}\s)/g, '$1\n\n$2')
  const html  = fixed ? DOMPurify.sanitize(marked.parse(fixed)) : ''

  return (
    <div>
      {debugEvents.length > 0 && (
        <div className={styles.debugPanel}>
          {debugEvents.map((e, i) => (
            <span key={i} className={styles.debugEvent}>
              {e.type === 'llm_call' ? `🧠 LLM #${e.value}` : `🔧 ${e.value}`}
            </span>
          ))}
        </div>
      )}
      {tools.map((t, i) => (
        <div key={i} className={styles.toolChip}>
          <span className={styles.toolDot} />{t}
        </div>
      ))}
      {clean
        ? <div className={styles.mdBody} dangerouslySetInnerHTML={{ __html: html }} />
        : <span className={styles.typing}><span /><span /><span /></span>
      }
      {/* 去掉光标，只在暂停时显示提示 */}
      {aborted && (
        <div className={styles.abortedHint}>
          <span className={styles.abortedDot} />
          已暂停回答
        </div>
      )}
    </div>
  )
}

// ── 侧边栏 ────────────────────────────────────────────────────
function Sidebar({ sessions, activeId, onSwitch, onNew, onDelete, collapsed, onToggle }) {
  return (
    <div className={`${styles.sidebar} ${collapsed ? styles.sidebarCollapsed : ''}`}>

      {/* 顶部：新建按钮 + 折叠按钮 */}
      <div className={styles.sidebarHead}>
        {!collapsed && <span className={styles.sidebarTitle}>会话记录</span>}
        <div className={styles.sidebarHeadBtns}>
          {!collapsed && (
            <button className={styles.newBtn} onClick={onNew} title="新建对话">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 5v14M5 12h14" strokeLinecap="round"/>
              </svg>
            </button>
          )}
          <button className={styles.collapseBtn} onClick={onToggle} title={collapsed ? '展开' : '收起'}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              {collapsed
                ? <path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round"/>
                : <path d="M15 18l-6-6 6-6" strokeLinecap="round" strokeLinejoin="round"/>
              }
            </svg>
          </button>
        </div>
      </div>

      {/* 会话列表 */}
      {!collapsed && (
        <div className={styles.sessionList}>
          {sessions.map(s => (
            <div
              key={s.id}
              className={`${styles.sessionItem} ${s.id === activeId ? styles.sessionActive : ''}`}
              onClick={() => onSwitch(s.id)}
            >
              <div className={styles.sessionIcon}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"
                    strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <div className={styles.sessionInfo}>
                <span className={styles.sessionTitle}>{s.title}</span>
                <span className={styles.sessionTime}>
                  {new Date(s.createdAt).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })}
                </span>
              </div>
              <button
                className={styles.deleteSessionBtn}
                onClick={(e) => onDelete(s.id, e)}
                title="删除"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round"/>
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── 欢迎页 ────────────────────────────────────────────────────
function WelcomeScreen({ onSend }) {
  return (
    <div className={styles.welcome}>
      <div className={styles.welcomeAvatar}>R</div>
      <h2 className={styles.welcomeTitle}>Rover</h2>
      <p className={styles.welcomeSub}>你的 AI 笔记助手，帮你搜索、回忆和总结笔记</p>
      <div className={styles.suggestions}>
        {SUGGESTIONS.map(s => (
          <button key={s} className={styles.suggestion} onClick={() => onSend(s)}>{s}</button>
        ))}
      </div>
    </div>
  )
}

// ── 消息列表 ──────────────────────────────────────────────────
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
            {msg.role === 'ai' && <div className={styles.aiAvatar}>R</div>}
            <div className={`${styles.bubble} ${msg.role === 'user' ? styles.userBubble : styles.aiBubble}`}>
              {msg.role === 'user'
                ? msg.content
                : <AiBubble
                    content={msg.content}
                    done={msg.done}
                    debugEvents={msg.debugEvents || []}
                    aborted={msg.aborted || false}
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

// ── 输入框 ────────────────────────────────────────────────────
function InputBar({ loading, onSend, onAbort }) {
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
          placeholder={loading ? 'Rover 正在回复...' : '问问 Rover...'}
          disabled={loading}
        />
        {/* loading 时显示暂停按钮，否则显示发送按钮 */}
        {loading ? (
          <button
            type="button"
            className={styles.stopBtn}
            onClick={onAbort}
            title="暂停回答"
          >
            <svg viewBox="0 0 24 24" fill="currentColor">
              <rect x="5" y="5" width="14" height="14" rx="3" />  {/* rx 加大，更圆润 */}
            </svg>
          </button>
        ) : (
          <button
            type="button"
            className={styles.sendBtn}
            onClick={handleSend}
            disabled={!input.trim()}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M22 2L11 13M22 2L15 22 11 13 2 9l20-7z" />
            </svg>
          </button>
        )}
      </div>
      <p className={styles.hint}>Rover 可能会出错，重要内容请自行核实</p>
    </div>
  )
}

// ── 主页面 ────────────────────────────────────────────────────
export default function ChatPage({ userId }) {
  const [collapsed, setCollapsed] = useState(false)

  const {
    sessions, activeId, messages, loading,
    sendMessage, clearHistory, newSession,
    deleteSession, switchSession, abortCurrent, isEmpty,
  } = useChat(userId)

  return (
    <div className={styles.page}>

      {/* 侧边栏 */}
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSwitch={switchSession}
        onNew={newSession}
        onDelete={deleteSession}
        collapsed={collapsed}
        onToggle={() => setCollapsed(v => !v)}
      />

      {/* 主聊天区 */}
      <div className={styles.chatArea}>
        {isEmpty
          ? <WelcomeScreen onSend={sendMessage} />
          : <MessageList messages={messages} onClear={clearHistory} />
        }
        <InputBar loading={loading} onSend={sendMessage} onAbort={abortCurrent} />
      </div>

    </div>
  )
}