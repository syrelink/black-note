import { useState } from 'react'
import { noteApi, fileApi } from '../api'
import styles from './PublishModal.module.css'

export default function PublishModal({ onClose, onSuccess }) {
  const [title,   setTitle]   = useState('')
  const [content, setContent] = useState('')
  const [images,  setImages]  = useState([])  // 已上传的URL列表
  const [uploading, setUploading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [msg, setMsg] = useState('')

  // 选择文件后自动上传
  const handleFile = async (e) => {
    const files = Array.from(e.target.files)
    if (!files.length) return
    setUploading(true)
    try {
      const urls = await Promise.all(files.map(f => fileApi.upload(f).then(r => r.data)))
      setImages(prev => [...prev, ...urls])
    } catch {
      setMsg('图片上传失败')
    } finally {
      setUploading(false)
    }
  }

  const removeImage = (idx) => {
    setImages(prev => prev.filter((_, i) => i !== idx))
  }

  const handleSubmit = async () => {
    if (!title.trim()) { setMsg('标题不能为空'); return }
    if (!content.trim()) { setMsg('内容不能为空'); return }
    setSubmitting(true)
    try {
      await noteApi.publish({ title, content, images })
      onSuccess()
      onClose()
    } catch {
      setMsg('发布失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <h2>发布笔记</h2>
          <button className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div className={styles.field}>
          <label>标题</label>
          <input
            type="text"
            placeholder="给笔记起个好标题..."
            value={title}
            onChange={e => setTitle(e.target.value)}
            maxLength={128}
          />
        </div>

        <div className={styles.field}>
          <label>内容</label>
          <textarea
            rows={5}
            placeholder="分享你的所见所闻..."
            value={content}
            onChange={e => setContent(e.target.value)}
          />
        </div>

        {/* 图片上传区 */}
        <div className={styles.field}>
          <label>图片 <span className={styles.hint}>（可多选）</span></label>
          <label className={styles.uploadArea}>
            <input
              type="file" accept="image/*" multiple
              style={{ display: 'none' }}
              onChange={handleFile}
            />
            {uploading
              ? <span className={styles.uploading}>上传中...</span>
              : <span>点击选择图片</span>
            }
          </label>

          {/* 已上传图片预览 */}
          {images.length > 0 && (
            <div className={styles.preview}>
              {images.map((url, i) => (
                <div key={i} className={styles.previewItem}>
                  <img src={url} alt="" />
                  <button onClick={() => removeImage(i)}>✕</button>
                </div>
              ))}
            </div>
          )}
        </div>

        {msg && <div className={styles.msg}>{msg}</div>}

        <div className={styles.actions}>
          <button className={styles.btnCancel} onClick={onClose}>取消</button>
          <button
            className={styles.btnSubmit}
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting ? '发布中...' : '发布'}
          </button>
        </div>
      </div>
    </div>
  )
}
