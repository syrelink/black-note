import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { noteApi, fileApi } from '../api'
import styles from './EditPage.module.css'

export default function EditPage() {
  const { id }    = useParams()
  const navigate  = useNavigate()

  const [title,     setTitle]     = useState('')
  const [content,   setContent]   = useState('')
  const [images,    setImages]    = useState([])
  const [uploading, setUploading] = useState(false)
  const [submitting,setSubmitting]= useState(false)
  const [loading,   setLoading]   = useState(true)
  const [preview,   setPreview]   = useState(false)
  const [msg,       setMsg]       = useState('')

  // 加载原始笔记数据
  useEffect(() => {
    noteApi.getById(id)
      .then(res => {
        const note = res.data
        setTitle(note.title || '')
        setContent(note.content || '')
        setImages(note.images || [])
      })
      .catch(() => setMsg('加载失败'))
      .finally(() => setLoading(false))
  }, [id])

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
      await noteApi.updateNote(id, { title, content, images })
      navigate(-1)
    } catch {
      setMsg('保存失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  const insertMd = (before, after = '') => {
    const ta = document.getElementById('md-editor-edit')
    const start = ta.selectionStart
    const end   = ta.selectionEnd
    const selected = content.slice(start, end)
    const newContent = content.slice(0, start) + before + selected + after + content.slice(end)
    setContent(newContent)
    setTimeout(() => {
      ta.focus()
      ta.setSelectionRange(start + before.length, start + before.length + selected.length)
    }, 0)
  }

  if (loading) return (
    <div className={styles.loading}>
      <div className={styles.spinner} />
    </div>
  )

  return (
    <div className={styles.page}>

      <div className={styles.header}>
        <button className={styles.back} onClick={() => navigate(-1)}>← 返回</button>
        <h2>编辑笔记</h2>
        <button className={styles.btnSubmit} onClick={handleSubmit} disabled={submitting}>
          {submitting ? '保存中...' : '保存'}
        </button>
      </div>

      {/* 标题 */}
      <div className={styles.field}>
        <label>标题</label>
        <input
          type="text"
          placeholder="标题..."
          value={title}
          onChange={e => setTitle(e.target.value)}
          maxLength={128}
        />
      </div>

      {/* Markdown 编辑器 */}
      <div className={styles.field}>
        <div className={styles.editorHeader}>
          <label>内容</label>
          <div className={styles.toolbar}>
            <button type="button" onClick={() => insertMd('**', '**')} title="粗体">B</button>
            <button type="button" onClick={() => insertMd('*', '*')}   title="斜体"><i>I</i></button>
            <button type="button" onClick={() => insertMd('## ')}      title="标题">H</button>
            <button type="button" onClick={() => insertMd('- ')}       title="列表">≡</button>
            <button type="button" onClick={() => insertMd('`', '`')}   title="代码">{`</>`}</button>
            <button type="button" onClick={() => insertMd('[', '](url)')} title="链接">🔗</button>
            <div className={styles.sep} />
            <button type="button" className={!preview ? styles.activeTab : ''} onClick={() => setPreview(false)}>编辑</button>
            <button type="button" className={preview  ? styles.activeTab : ''} onClick={() => setPreview(true)}>预览</button>
          </div>
        </div>

        {preview ? (
          <div
            className={styles.mdPreview}
            dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
          />
        ) : (
          <textarea
            id="md-editor-edit"
            rows={16}
            placeholder="支持 Markdown 语法..."
            value={content}
            onChange={e => setContent(e.target.value)}
            className={styles.mdEditor}
          />
        )}
      </div>

      {/* 图片 */}
      <div className={styles.field}>
        <label>图片 <span className={styles.hint}>（可多选）</span></label>
        <label className={styles.uploadArea}>
          <input type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={handleFile} />
          {uploading ? <span>上传中...</span> : <span>点击选择图片</span>}
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