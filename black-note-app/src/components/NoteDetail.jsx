import { useState, useEffect, useRef } from 'react'
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

  const [detail,   setDetail]   = useState(note)
  const [imgIndex, setImgIndex] = useState(0)
  const [deleting, setDeleting] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false) 

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

  if (!note) return null

  const images = detail?.images || []
  const hasImg = images.length > 0

  const prevImg = (e) => { e.stopPropagation(); setImgIndex(i => Math.max(i - 1, 0)) }
  const nextImg = (e) => { e.stopPropagation(); setImgIndex(i => Math.min(i + 1, images.length - 1)) }

  const handleTouchStart = (e) => { touchStartX.current = e.touches[0].clientX }
  const handleTouchEnd   = (e) => {
    touchEndX.current = e.changedTouches[0].clientX
    const diff = touchStartX.current - touchEndX.current
    if (diff > 50)  nextImg(e)
    if (diff < -50) prevImg(e)
  }

  const handleLike = () => {
    if (!isLogin) return
    onLike(note.id)
  }

  const handleEdit = () => {
    onClose()
    navigate(`/note/edit/${note.id}`)
  }

  // 点删除按钮：只弹出自定义确认框
  const handleDelete = () => {
    setShowConfirm(true)
  }

  // 用户点确认：真正执行删除
  const handleConfirmDelete = async () => {
    setDeleting(true)
    try {
      await noteApi.deleteNote(note.id)
      setShowConfirm(false)
      onClose()           // 关闭详情弹窗
      onDeleted?.(note.id) // 通知父组件删除这条笔记
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
    <div className={styles.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>

        {/* 左侧图片轮播：没有图片就不渲染 */}
        {hasImg && (
          <div className={styles.left} onTouchStart={handleTouchStart} onTouchEnd={handleTouchEnd}>
            <div className={styles.imgTrack}>
              {images.map((url, i) => (
                <img
                  key={i} src={url} alt={`图片${i + 1}`}
                  className={styles.slideImg}
                  style={{ transform: `translateX(${(i - imgIndex) * 100}%)` }}
                />
              ))}
            </div>
            {images.length > 1 && (
              <>
                <button className={`${styles.arrow} ${styles.arrowLeft}`}  onClick={prevImg} disabled={imgIndex === 0}>‹</button>
                <button className={`${styles.arrow} ${styles.arrowRight}`} onClick={nextImg} disabled={imgIndex === images.length - 1}>›</button>
                <div className={styles.dots}>
                  {images.map((_, i) => (
                    <button key={i} className={`${styles.dot} ${i === imgIndex ? styles.dotActive : ''}`}
                      onClick={e => { e.stopPropagation(); setImgIndex(i) }} />
                  ))}
                </div>
                <div className={styles.counter}>{imgIndex + 1} / {images.length}</div>
              </>
            )}
          </div>
        )}

        {/* 右侧内容 */}
        <div className={`${styles.right} ${!hasImg ? styles.rightFull : ''}`}>

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

          <h2 className={styles.title}>{detail?.title}</h2>

          {/* MDEditor 渲染 Markdown */}
          <div className={styles.content} data-color-mode="light">
            <MDEditor.Markdown
              source={detail?.content || ''}
              remarkPlugins={[remarkMath]}
              rehypePlugins={[rehypeKatex]}
            />
          </div>

          {/* 底部操作栏 */}
          <div className={styles.actions}>
            <button
              className={`${styles.likeBtn} ${liked ? styles.liked : ''}`}
              onClick={handleLike}
            >
              {liked ? '♥' : '♡'} <span>{count}</span> 点赞
            </button>

            {isAuthor && (
              <div className={styles.authorActions}>
                <button className={styles.editBtn} onClick={handleEdit}>编辑</button>
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