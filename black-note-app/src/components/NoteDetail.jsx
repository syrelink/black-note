import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import MDEditor from '@uiw/react-md-editor'
import ConfirmModal from './ConfirmModal'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { noteApi } from '../api'
import { useAuth } from '../hooks/useAuth'
import styles from './NoteDetail.module.css'

export default function NoteDetail({ note, onClose, onLike, likeMap, onDeleted }) {
  const { isLogin, userInfo } = useAuth()
  const navigate = useNavigate()

  const liked = likeMap?.[note?.id]?.liked ?? !!note?.isLiked
  const count = likeMap?.[note?.id]?.count ?? note?.likeCount ?? 0

  const [detail,      setDetail]      = useState(note)
  const [imgIndex,    setImgIndex]    = useState(0)
  const [deleting,    setDeleting]    = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)

  const [leftPct, setLeftPct] = useState(50)
  const dragging   = useRef(false)
  const modalRef   = useRef(null)

  const touchStartX = useRef(0)
  const touchEndX   = useRef(0)

  const isAuthor = userInfo?.id && detail?.userId && String(userInfo.id) === String(detail.userId)

  useEffect(() => {
    if (!note) return
    setDetail(note)
    setImgIndex(0)
    noteApi.getById(note.id)
      .then(res => { if (res.data) setDetail(res.data) })
      .catch(() => {})
  }, [note])

  const onDividerMouseDown = useCallback((e) => {
    e.preventDefault()
    dragging.current = true
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [])

  useEffect(() => {
    const onMove = (e) => {
      if (!dragging.current || !modalRef.current) return
      const rect = modalRef.current.getBoundingClientRect()
      const x = (e.clientX ?? e.touches?.[0]?.clientX) - rect.left
      const pct = Math.min(Math.max((x / rect.width) * 100, 25), 75)
      setLeftPct(pct)
    }
    const onUp = () => {
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup',   onUp)
    window.addEventListener('touchmove', onMove, { passive: true })
    window.addEventListener('touchend',  onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup',   onUp)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend',  onUp)
    }
  }, [])

  if (!note) return null

  const images  = detail?.images || []
  const hasImg  = images.length > 0

  const prevImg = (e) => { e.stopPropagation(); setImgIndex(i => Math.max(i - 1, 0)) }
  const nextImg = (e) => { e.stopPropagation(); setImgIndex(i => Math.min(i + 1, images.length - 1)) }

  const handleTouchStart = (e) => { touchStartX.current = e.touches[0].clientX }
  const handleTouchEnd   = (e) => {
    touchEndX.current = e.changedTouches[0].clientX
    const diff = touchStartX.current - touchEndX.current
    if (diff > 50)  nextImg(e)
    if (diff < -50) prevImg(e)
  }

  const handleLike   = () => { if (!isLogin) return; onLike(note.id) }
  const handleEdit   = () => { onClose(); navigate(`/note/edit/${note.id}`) }
  const handleDelete = () => setShowConfirm(true)

  const handleConfirmDelete = async () => {
    setDeleting(true)
    try {
      await noteApi.deleteNote(note.id)
      setShowConfirm(false)
      onClose()
      onDeleted?.(note.id)
    } catch {
      alert('删除失败，请重试')
    } finally {
      setDeleting(false)
    }
  }

  const handleAuthorClick = () => {
    if (detail?.userId) { onClose(); navigate(`/user/${detail.userId}`) }
  }

  return (
    <div className={styles.overlay}>
      <div className={styles.modal} ref={modalRef}>

        {/* 左侧图片区 */}
        {hasImg && (
          <div
            className={styles.left}
            style={{ width: `${leftPct}%` }}
            onTouchStart={handleTouchStart}
            onTouchEnd={handleTouchEnd}
          >
            <div className={styles.imgScroll}>
              {images.map((url, i) => (
                <div key={i} className={styles.imgSlide}>
                  <img src={url} alt={`图片${i + 1}`} className={styles.slideImg} />
                </div>
              ))}
            </div>

            {images.length > 1 && (
              <>
                <button className={`${styles.arrow} ${styles.arrowLeft}`}  onClick={prevImg} disabled={imgIndex === 0}>‹</button>
                <button className={`${styles.arrow} ${styles.arrowRight}`} onClick={nextImg} disabled={imgIndex === images.length - 1}>›</button>
                <div className={styles.dots}>
                  {images.map((_, i) => (
                    <button key={i}
                      className={`${styles.dot} ${i === imgIndex ? styles.dotActive : ''}`}
                      onClick={e => { e.stopPropagation(); setImgIndex(i) }}
                    />
                  ))}
                </div>
                <div className={styles.counter}>{imgIndex + 1} / {images.length}</div>
              </>
            )}
          </div>
        )}

        {/* 拖拽分隔线 */}
        {hasImg && (
          <div className={styles.divider} onMouseDown={onDividerMouseDown} onTouchStart={onDividerMouseDown}>
            <div className={styles.dividerHandle} />
          </div>
        )}

        {/* 右侧内容区 */}
        <div className={`${styles.right} ${!hasImg ? styles.rightFull : ''}`}>
          <button className={styles.closeBtn} onClick={onClose}>✕</button>

          {/* 顶部固定：作者信息，外层不可点击 */}
          <div className={styles.author}>

            {/* 头像：点击跳转，hover 只在自身生效 */}
            <div className={styles.avatar} onClick={handleAuthorClick}>
              {detail?.authorAvatar
                ? <img src={detail.authorAvatar} alt={detail.authorName} />
                : <span>{detail?.authorName?.charAt(0) || '?'}</span>
              }
            </div>

            {/* 昵称+时间：点击跳转，hover 只在自身生效 */}
            <div className={styles.authorInfo} onClick={handleAuthorClick}>
              <div className={styles.authorName}>{detail?.authorName || '匿名用户'}</div>
              <div className={styles.time}>{detail?.createdAt?.slice(0, 10) || ''}</div>
            </div>

          </div>

          {/* 中间滚动区：标题 + 正文 */}
          <div className={styles.scrollBody}>
            <h2 className={styles.title}>{detail?.title}</h2>
            <div className={styles.content} data-color-mode="light">
              <MDEditor.Markdown
                source={detail?.content || ''}
                remarkPlugins={[remarkMath]}
                rehypePlugins={[rehypeKatex]}
              />
            </div>
          </div>

          {/* 底部固定：点赞 + 编辑 + 删除 */}
          <div className={styles.actions}>
            <button
              className={`${styles.likeBtn} ${liked ? styles.liked : ''}`}
              onClick={handleLike}
            >
              {liked ? '♥' : '♡'} <span>{count}</span> 点赞
            </button>

            {isAuthor && (
              <div className={styles.authorActions}>
                <button className={styles.editBtn}   onClick={handleEdit}>编辑</button>
                <button className={styles.deleteBtn} onClick={handleDelete} disabled={deleting}>
                  {deleting ? '删除中...' : '删除'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {showConfirm && (
        <ConfirmModal
          title="删除笔记"
          message="确认删除这篇笔记？删除后无法恢复。"
          loading={deleting}
          onConfirm={handleConfirmDelete}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  )
}