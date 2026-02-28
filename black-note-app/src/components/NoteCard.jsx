import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { noteApi } from '../api'
import { useAuth } from '../hooks/useAuth'
import styles from './NoteCard.module.css'

export default function NoteCard({ note, onClick, index , onLike, likeMap}) {
  const { isLogin } = useAuth()
  const navigate    = useNavigate()
  const liked = likeMap?.[note?.id]?.liked ?? !!note?.isLiked
  const count = likeMap?.[note?.id]?.count ?? note?.likeCount ?? 0
  const [imgErr,  setImgErr]  = useState(false)

  const hasImg = note.images?.length > 0 && !imgErr


  const handleLike = (e) => {
    e.stopPropagation()
    if (!isLogin) return
    onLike(note.id)  // 交给父组件处理
  }

  // 点击作者区域跳转用户主页
  const handleAuthorClick = (e) => {
    e.stopPropagation()
    if (note.userId) navigate(`/user/${note.userId}`)
  }

  return (
    <div
      className={styles.card}
      style={{ animationDelay: `${index * 0.04}s` }}
      onClick={() => onClick(note)}
    >
      {hasImg && (
        <img
          className={styles.img}
          src={note.images[0]}
          alt={note.title}
          loading="lazy"
          onError={() => setImgErr(true)}
        />
      )}

      <div className={styles.body}>
        <div className={styles.title}>{note.title}</div>
        <div className={styles.excerpt} 
        dangerouslySetInnerHTML={{ __html: renderMarkdown(note.content || '') }}/>

        <div className={styles.footer}>
          {/* 作者信息：点击跳转用户主页 */}
          <div className={styles.author} onClick={handleAuthorClick}>
            <div className={styles.avatar}>
              {note.authorAvatar
                ? <img src={note.authorAvatar} alt={note.authorName} />
                : <span>{note.authorName?.charAt(0) || '?'}</span>
              }
            </div>
            <span className={styles.authorName}>
              {note.authorName || '匿名用户'}
            </span>
          </div>

          {/* 点赞按钮 */}
          <button
            className={`${styles.like} ${liked ? styles.liked : ''}`}
            onClick={handleLike}
          >
            {liked ? '♥' : '♡'} {count}
          </button>
        </div>
      </div>
    </div>
  )
}

function renderMarkdown(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^## (.+)$/gm,    '<h2>$1</h2>')
    .replace(/^### (.+)$/gm,   '<h3>$1</h3>')
    .replace(/^# (.+)$/gm,     '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,     '<em>$1</em>')
    .replace(/`(.+?)`/g,       '<code>$1</code>')
    .replace(/^- (.+)$/gm,     '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gs,'<ul>$1</ul>')
    .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank">$1</a>')
    .replace(/\n/g, '<br/>')
}