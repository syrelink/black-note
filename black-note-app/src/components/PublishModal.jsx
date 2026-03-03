import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import 'katex/dist/katex.min.css'
import 'highlight.js/styles/github.css'
import { noteApi, fileApi } from '../api'
import styles from './PublishModal.module.css'

// 和 EditPage 完全一致的预览组件
function MarkdownPreview({ content, className }) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex, rehypeHighlight]}
      >
        {content || ' '}
      </ReactMarkdown>
    </div>
  )
}

export default function PublishModal({ onClose, onSuccess }) {
  const [title,      setTitle]      = useState('')
  const [content,    setContent]    = useState('')
  const [images,     setImages]     = useState([])
  const [uploading,  setUploading]  = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [msg,        setMsg]        = useState('')
  const [mode,       setMode]       = useState('edit') // 'edit' | 'split' | 'preview'

  const textareaRef = useRef(null)

  // 自动撑高 textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.max(ta.scrollHeight, 300) + 'px'
  }, [content, mode])

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
    // ★ 不加 onClick，点击遮罩不关闭，只能点 ✕ 按钮关闭
    <div className={styles.overlay}>
      <div className={styles.modal}>

        {/* ── 顶部栏：标题 + 模式切换 + 关闭 ── */}
        <div className={styles.header}>
          <input
            className={styles.titleInput}
            type="text"
            placeholder="给笔记起个好标题..."
            value={title}
            onChange={e => setTitle(e.target.value)}
            maxLength={128}
          />

          <div className={styles.modeSwitch}>
            {[
              { key: 'edit',    label: '编辑' },
              { key: 'split',   label: '分栏' },
              { key: 'preview', label: '预览' },
            ].map(({ key, label }) => (
              <button
                key={key}
                className={`${styles.modeBtn} ${mode === key ? styles.modeActive : ''}`}
                onClick={() => setMode(key)}
              >{label}</button>
            ))}
          </div>

          <button className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div className={styles.headerDivider} />

        {/* ── 编辑器主区域 ── */}
        <div className={`${styles.editorWrap} ${styles['mode_' + mode]}`}>

          {/* 编辑区 */}
          {(mode === 'edit' || mode === 'split') && (
            <div className={styles.editPane}>
              <textarea
                ref={textareaRef}
                className={styles.editor}
                value={content}
                onChange={e => setContent(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={`开始写作...\n\n支持完整 Markdown + LaTeX：\n# 一级标题\n## 二级标题\n**粗体**  *斜体*  \`行内代码\`\n\n- 无序列表\n1. 有序列表\n\n| 表头A | 表头B |\n|-------|-------|\n| 内容  | 内容  |\n\n> 引用块\n\n行内公式：$E = mc^2$\n块级公式：\n$$\n\\int_{-\\infty}^{\\infty} e^{-x^2} dx = \\sqrt{\\pi}\n$$`}
              />
            </div>
          )}

          {/* 分栏分割线 */}
          {mode === 'split' && <div className={styles.splitLine} />}

          {/* 预览区 */}
          {(mode === 'preview' || mode === 'split') && (
            <MarkdownPreview
              content={content}
              className={styles.previewPane}
            />
          )}
        </div>

        {/* ── 底部：图片 + 操作按钮 ── */}
        <div className={styles.footer}>
          <div className={styles.imageRow}>
            <label className={styles.uploadBtn}>
              <input type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={handleFile} />
              {uploading ? '上传中' : '+ 图片'}
            </label>
            {images.map((url, i) => (
              <div key={i} className={styles.imgThumb}>
                <img src={url} alt="" />
                <button onClick={() => removeImage(i)}>✕</button>
              </div>
            ))}
          </div>

          <div className={styles.footerActions}>
            {msg && <span className={styles.msg}>{msg}</span>}
            <button className={styles.btnCancel} onClick={onClose}>取消</button>
            <button className={styles.btnSubmit} onClick={handleSubmit} disabled={submitting}>
              {submitting ? '发布中...' : '发布'}
            </button>
          </div>
        </div>

      </div>
    </div>
  )
}