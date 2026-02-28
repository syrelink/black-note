import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { noteApi } from '../api'
import { useAuth } from '../hooks/useAuth'
import styles from './NoteCard.module.css'

export default function NoteCard({ note, onClick, index }) {
  const { isLogin } = useAuth()
  const navigate    = useNavigate()

  const [liked,   setLiked]   = useState(false)
  const [count,   setCount]   = useState(note.likeCount || 0)
  const [imgErr,  setImgErr]  = useState(false)

  const hasImg = note.images?.length > 0 && !imgErr

  // 登录后从后端拉取点赞状态，刷新后也能恢复
  useEffect(() => {
    if (!isLogin || !note.id) return
    noteApi.isLiked(note.id)
      .then(res => setLiked(!!res.data))
      .catch(() => {})
  }, [note.id, isLogin])

  // 同步后端返回的最新点赞数
  useEffect(() => {
    setCount(note.likeCount || 0)
  }, [note.likeCount])

  const handleLike = async (e) => {
    e.stopPropagation()
    if (!isLogin) return
    try {
      await noteApi.like(note.id)
      const newLiked = !liked
      setLiked(newLiked)
      setCount(prev => newLiked ? prev + 1 : prev - 1)
    } catch {}
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
        <div className={styles.excerpt}>{note.content}</div>

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