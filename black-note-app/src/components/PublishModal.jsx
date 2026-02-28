import { useState } from 'react'
import { noteApi, fileApi } from '../api'
import styles from './PublishModal.module.css'

export default function PublishModal({ onClose, onSuccess }) {
  const [title,     setTitle]     = useState('')
  const [content,   setContent]   = useState('')
  const [images,    setImages]    = useState([])
  const [uploading, setUploading] = useState(false)
  const [submitting,setSubmitting]= useState(false)
  const [msg,       setMsg]       = useState('')
  const [preview,   setPreview]   = useState(false)  // 是否预览模式

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

  const removeImage = (idx) => setImages(prev => prev.filter((_, i) => i !== idx))

  const handleSubmit = async () => {
    if (!title.trim())   { setMsg('标题不能为空'); return }
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

  // 插入 Markdown 语法到光标位置
  const insertMd = (before, after = '') => {
    const ta = document.getElementById('md-editor')
    const start = ta.selectionStart
    const end   = ta.selectionEnd
    const selected = content.slice(start, end)
    const newContent =
      content.slice(0, start) + before + selected + after + content.slice(end)
    setContent(newContent)
    setTimeout(() => {
      ta.focus()
      ta.setSelectionRange(start + before.length, start + before.length + selected.length)
    }, 0)
  }

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>

        <div className={styles.header}>
          <h2>发布笔记</h2>
          <button className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        {/* 标题 */}
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

        {/* Markdown 编辑器 */}
        <div className={styles.field}>
          <div className={styles.editorHeader}>
            <label>内容</label>
            {/* 工具栏 */}
            <div className={styles.toolbar}>
              <button type="button" onClick={() => insertMd('**', '**')} title="粗体">B</button>
              <button type="button" onClick={() => insertMd('*', '*')}   title="斜体"><i>I</i></button>
              <button type="button" onClick={() => insertMd('## ')}      title="标题">H</button>
              <button type="button" onClick={() => insertMd('- ')}       title="列表">≡</button>
              <button type="button" onClick={() => insertMd('`', '`')}   title="代码">{`</>`}</button>
              <button type="button" onClick={() => insertMd('[', '](url)')} title="链接">🔗</button>
              <div className={styles.sep} />
              <button className={!preview ? styles.activeTab : ''} onClick={() => setPreview(false)}>编辑</button>
              <button className={preview  ? styles.activeTab : ''} onClick={() => setPreview(true)}>预览</button>
            </div>
          </div>

          {preview ? (
            // 预览模式：渲染 Markdown
            <div
              className={styles.mdPreview}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
            />
          ) : (
            // 编辑模式
            <textarea
              id="md-editor"
              rows={10}
              placeholder={'支持 Markdown 语法\n\n**粗体** *斜体* ## 标题\n- 列表\n`代码`'}
              value={content}
              onChange={e => setContent(e.target.value)}
              className={styles.mdEditor}
            />
          )}
        </div>

        {/* 图片上传 */}
        <div className={styles.field}>
          <label>图片 <span className={styles.hint}>（可多选）</span></label>
          <label className={styles.uploadArea}>
            <input type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={handleFile} />
            {uploading ? <span className={styles.uploading}>上传中...</span> : <span>点击选择图片</span>}
          </label>
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
          <button className={styles.btnSubmit} onClick={handleSubmit} disabled={submitting}>
            {submitting ? '发布中...' : '发布'}
          </button>
        </div>

      </div>
    </div>
  )
}

// 简易 Markdown 渲染（不依赖额外库）
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