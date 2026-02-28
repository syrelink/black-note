import { useState, useRef, useEffect } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { noteApi, fileApi } from '../api'
import styles from './PublishModal.module.css'

function renderKatex(formula, displayMode) {
  try {
    return katex.renderToString(formula, { displayMode, throwOnError: false, output: 'html' })
  } catch { return formula }
}

function renderMarkdown(text) {
  if (!text) return ''
  const blocks = []
  const BP = '___BLK___', IP = '___INL___'

  let r = text
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, f) => { blocks.push(renderKatex(f.trim(), true));  return `${BP}${blocks.length-1}___` })
    .replace(/\$([^\n$]+?)\$/g,     (_, f) => { blocks.push(renderKatex(f.trim(), false)); return `${IP}${blocks.length-1}___` })

  r = r
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/^#{3} (.+)$/gm,'<h3>$1</h3>')
    .replace(/^#{2} (.+)$/gm,'<h2>$1</h2>')
    .replace(/^#{1} (.+)$/gm,'<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/`{3}([\s\S]*?)`{3}/g,'<pre><code>$1</code></pre>')
    .replace(/`(.+?)`/g,'<code>$1</code>')
    .replace(/^> (.+)$/gm,'<blockquote>$1</blockquote>')
    .replace(/^- (.+)$/gm,'<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>)/g,'<ul>$1</ul>')
    .replace(/\[(.+?)\]\((.+?)\)/g,'<a href="$2" target="_blank">$1</a>')
    .replace(/---/g,'<hr/>')
    .replace(/\n/g,'<br/>')

  r = r.replace(new RegExp(`(${BP}|${IP})(\\d+)___`,'g'), (_,__,i) => blocks[parseInt(i)])
  return r
}

export default function PublishModal({ onClose, onSuccess }) {
  const [title,      setTitle]     = useState('')
  const [content,    setContent]   = useState('')
  const [images,     setImages]    = useState([])
  const [uploading,  setUploading] = useState(false)
  const [submitting, setSubmitting]= useState(false)
  const [msg,        setMsg]       = useState('')
  const [tab,        setTab]       = useState('edit') // 'edit' | 'preview'

  const textareaRef = useRef(null)

  // 自动撑高 textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.max(ta.scrollHeight, 220) + 'px'
  }, [content])

  const handleKeyDown = (e) => {
    if (e.key === 'Tab') {
      e.preventDefault()
      const s = e.target.selectionStart
      const newVal = content.substring(0, s) + '  ' + content.substring(e.target.selectionEnd)
      setContent(newVal)
      setTimeout(() => { e.target.selectionStart = e.target.selectionEnd = s + 2 }, 0)
    }
  }

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
    setMsg('')
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

        {/* 顶部 */}
        <div className={styles.header}>
          <input
            className={styles.titleInput}
            type="text"
            placeholder="给笔记起个好标题..."
            value={title}
            onChange={e => setTitle(e.target.value)}
            maxLength={128}
          />
          <button className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div className={styles.divider} />

        {/* 编辑/预览切换 */}
        <div className={styles.tabBar}>
          <button
            className={`${styles.tabBtn} ${tab === 'edit' ? styles.tabActive : ''}`}
            onClick={() => setTab('edit')}
          >编辑</button>
          <button
            className={`${styles.tabBtn} ${tab === 'preview' ? styles.tabActive : ''}`}
            onClick={() => setTab('preview')}
          >预览</button>
          <span className={styles.tabHint}>支持 Markdown · LaTeX 公式</span>
        </div>

        {/* 内容区 */}
        <div className={styles.editorArea}>
          {tab === 'edit' ? (
            <textarea
              ref={textareaRef}
              className={styles.editor}
              value={content}
              onChange={e => setContent(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`开始写作...\n\n# 标题  **粗体**  *斜体*\n- 列表项\n> 引用\n\n行内公式：$E=mc^2$\n块级公式：$$\\int f(x)dx$$`}
            />
          ) : (
            <div
              className={styles.preview}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(content) || '<span class="' + styles.previewEmpty + '">暂无内容</span>' }}
            />
          )}
        </div>

        {/* 图片上传 */}
        <div className={styles.imageRow}>
          <label className={styles.uploadBtn}>
            <input type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={handleFile} />
            {uploading ? '上传中...' : '+ 添加图片'}
          </label>

          {images.map((url, i) => (
            <div key={i} className={styles.imgThumb}>
              <img src={url} alt="" />
              <button onClick={() => removeImage(i)}>✕</button>
            </div>
          ))}
        </div>

        {msg && <div className={styles.msg}>{msg}</div>}

        {/* 底部操作 */}
        <div className={styles.footer}>
          <button className={styles.btnCancel} onClick={onClose}>取消</button>
          <button className={styles.btnSubmit} onClick={handleSubmit} disabled={submitting}>
            {submitting ? '发布中...' : '发布'}
          </button>
        </div>

      </div>
    </div>
  )
}