import { useState, useRef, useEffect } from 'react'
import styles from './AiChat.module.css'

export default function AiChat({ userId }) {
  const [messages, setMessages] = useState([
    { role: 'ai', content: '你好！我是你的笔记助手，可以帮你搜索和总结笔记 📝' }
  ])
  const [input,   setInput]   = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)

  // 自动滚到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async () => {
    if (!input.trim() || loading) return
    const question = input.trim()
    setInput('')
    setLoading(true)

    // 加入用户消息
    setMessages(prev => [...prev, { role: 'user', content: question }])
    // 加入AI消息占位
    setMessages(prev => [...prev, { role: 'ai', content: '' }])

    try {
      const token = localStorage.getItem('token')
      const res = await fetch(
        `/api/ai/chat`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': token  // ← 去掉 Bearer，直接用token
          },
          body: JSON.stringify({
            question:   question,
            session_id: 'home'
          })
        }
      )

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const lines = decoder.decode(value).split('\n')
        console.log('收到原始数据:', lines)  // ← 加这行
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const content = line.slice(5).trim()
          if (content === '[DONE]' || content === '[ERROR]') break

          setMessages(prev => {
            const updated = [...prev]
            updated[updated.length - 1] = {
              ...updated[updated.length - 1],
              content: updated[updated.length - 1].content + content
            }
            return updated
          })
        }
      }
    } catch (e) {
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1].content = '请求失败，请稍后重试'
        return updated
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.headerIcon}>✨</span>
        <span>AI 笔记助手</span>
      </div>

      <div className={styles.messages}>
        {messages.map((msg, i) => (
          <div key={i} className={`${styles.row} ${msg.role === 'user' ? styles.userRow : styles.aiRow}`}>
            {msg.role === 'ai' && <div className={styles.avatar}>AI</div>}
            <div className={`${styles.bubble} ${msg.role === 'user' ? styles.userBubble : styles.aiBubble}`}>
              {msg.content || <span className={styles.typing}>···</span>}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className={styles.inputArea}>
        <input
          className={styles.input}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
          placeholder="问问你的笔记助手..."
          disabled={loading}
        />
        <button
          className={styles.sendBtn}
          onClick={sendMessage}
          disabled={loading || !input.trim()}
        >
          {loading ? '···' : '发送'}
        </button>
      </div>
    </div>
  )
}