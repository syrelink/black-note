import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { noteApi } from '../api'
import { useAuth } from '../hooks/useAuth'
import styles from './NoteDetail.module.css'

export default function NoteDetail({ note, onClose }) {
  const { isLogin } = useAuth()
  const navigate    = useNavigate()

  const [liked,    setLiked]    = useState(false)
  const [count,    setCount]    = useState(note?.likeCount || 0)
  const [detail,   setDetail]   = useState(note)
  const [imgIndex, setImgIndex] = useState(0)  // 当前显示第几张图

  // 触摸滑动
  const touchStartX = useRef(0)
  const touchEndX   = useRef(0)

  useEffect(() => {
    if (!note) return
    setDetail(note)
    setCount(note.likeCount || 0)
    setLiked(!!note.isLiked)
    setImgIndex(0)  // 切换笔记时重置图片索引

    noteApi.getById(note.id)
      .then(res => {
        if (res.data) {
          setDetail(res.data)
          setCount(res.data.likeCount || 0)
          setLiked(!!res.data.isLiked)
        }
      })
      .catch(() => {})
  }, [note])

  if (!note) return null

  const images = detail?.images || []
  const hasImg = images.length > 0

  // 切换图片
  const prevImg = (e) => {
    e.stopPropagation()
    setImgIndex(i => Math.max(i - 1, 0))
  }
  const nextImg = (e) => {
    e.stopPropagation()
    setImgIndex(i => Math.min(i + 1, images.length - 1))
  }

  // 触摸滑动
  const handleTouchStart = (e) => { touchStartX.current = e.touches[0].clientX }
  const handleTouchEnd   = (e) => {
    touchEndX.current = e.changedTouches[0].clientX
    const diff = touchStartX.current - touchEndX.current
    if (diff > 50)  nextImg(e)   // 左滑 → 下一张
    if (diff < -50) prevImg(e)   // 右滑 → 上一张
  }

  const handleLike = async () => {
    if (!isLogin) return
    try {
      await noteApi.like(note.id)
      setLiked(prevLiked => {
        const newLiked = !prevLiked
        setCount(prevCount => newLiked ? prevCount + 1 : prevCount - 1)
        return newLiked
      })
    } catch {}
  }

  const handleAuthorClick = () => {
    if (detail?.userId) { onClose(); navigate(`/user/${detail.userId}`) }
  }

  return (
    <div className={styles.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>

        {/* ── 左侧：图片轮播 ── */}
        <div
          className={styles.left}
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
        >
          {hasImg ? (
            <>
              {/* 图片主体 */}
              <div className={styles.imgTrack}>
                {images.map((url, i) => (
                  <img
                    key={i}
                    src={url}
                    alt={`图片${i + 1}`}
                    className={styles.slideImg}
                    style={{ transform: `translateX(${(i - imgIndex) * 100}%)` }}
                  />
                ))}
              </div>

              {/* 左右切换箭头（多于1张才显示）*/}
              {images.length > 1 && (
                <>
                  <button
                    className={`${styles.arrow} ${styles.arrowLeft}`}
                    onClick={prevImg}
                    disabled={imgIndex === 0}
                  >‹</button>
                  <button
                    className={`${styles.arrow} ${styles.arrowRight}`}
                    onClick={nextImg}
                    disabled={imgIndex === images.length - 1}
                  >›</button>

                  {/* 底部圆点指示器 */}
                  <div className={styles.dots}>
                    {images.map((_, i) => (
                      <button
                        key={i}
                        className={`${styles.dot} ${i === imgIndex ? styles.dotActive : ''}`}
                        onClick={(e) => { e.stopPropagation(); setImgIndex(i) }}
                      />
                    ))}
                  </div>

                  {/* 右上角计数 */}
                  <div className={styles.counter}>
                    {imgIndex + 1} / {images.length}
                  </div>
                </>
              )}
            </>
          ) : (
            <span className={styles.noImg}>📝</span>
          )}
        </div>

        {/* ── 右侧：内容区 ── */}
        <div className={styles.right}>
          <button className={styles.closeBtn} onClick={onClose}>✕</button>

          {/* 作者信息 */}
          <div className={styles.author} onClick={handleAuthorClick}>
            <div className={styles.avatar}>
              {detail?.authorAvatar
                ? <img src={detail.authorAvatar} alt={detail.authorName} />
                : <span>{detail?.authorName?.charAt(0) || '?'}</span>
              }
            </div>
            <div>
              <div className={styles.authorName}>{detail?.authorName || '匿名用户'}</div>
              <div className={styles.time}>{detail?.createdAt?.slice(0, 10) || ''}</div>
            </div>
          </div>

          {/* 标题 */}
          <h2 className={styles.title}>{detail?.title}</h2>

          {/* 正文 */}
          <p className={styles.content}>{detail?.content}</p>

          {/* 操作栏 */}
          <div className={styles.actions}>
            <button
              className={`${styles.likeBtn} ${liked ? styles.liked : ''}`}
              onClick={handleLike}
            >
              {liked ? '♥' : '♡'} <span>{count}</span> 点赞
            </button>
          </div>
        </div>

      </div>
    </div>
  )
}