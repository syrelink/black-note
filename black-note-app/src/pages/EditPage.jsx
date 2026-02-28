import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { noteApi, fileApi } from '../api'
import styles from './EditPage.module.css'

// 渲染单个公式，出错时原样返回
function renderKatex(formula, displayMode) {
  try {
    return katex.renderToString(formula, {
      displayMode,
      throwOnError: false,
      output: 'html',
    })
  } catch {
    return formula
  }
}

// Markdown + LaTeX 渲染
function renderMarkdown(text) {
  if (!text) return ''

  // 第一步：把公式占位，避免被 Markdown 规则破坏
  const blocks   = []  // 存公式 HTML
  const BLOCK_PH = '___BLOCK_FORMULA___'
  const INLINE_PH = '___INLINE_FORMULA___'

  // 替换块级公式 $$ ... $$
  let result = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, formula) => {
    blocks.push({ html: renderKatex(formula.trim(), true), type: 'block' })
    return `${BLOCK_PH}${blocks.length - 1}___`
  })

  // 替换行内公式 $ ... $
  result = result.replace(/\$([^\n$]+?)\$/g, (_, formula) => {
    blocks.push({ html: renderKatex(formula.trim(), false), type: 'inline' })
    return `${INLINE_PH}${blocks.length - 1}___`
  })

  // 第二步：正常 Markdown 处理
  result = result
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^#{3} (.+)$/gm, '<h3>$1</h3>')
    .replace(/^#{2} (.+)$/gm, '<h2>$1</h2>')
    .replace(/^#{1} (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`{3}([\s\S]*?)`{3}/g, '<pre><code>$1</code></pre>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>')
    .replace(/^\d+\. (.+)$/gm, '<oli>$1</oli>')
    .replace(/(<oli>[\s\S]*?<\/oli>)/g, '<ol>$1</ol>')
    .replace(/<oli>/g, '<li>').replace(/<\/oli>/g, '</li>')
    .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank">$1</a>')
    .replace(/!\[(.+?)\]\((.+?)\)/g, '<img src="$2" alt="$1" />')
    .replace(/---/g, '<hr/>')
    .replace(/\n\n/g, '<br/>')
    .replace(/\n/g, '<br/>')

  // 第三步：把公式还原回来
  result = result.replace(
    new RegExp(`(${BLOCK_PH}|${INLINE_PH})(\\d+)___`, 'g'),
    (_, __, idx) => blocks[parseInt(idx)].html
  )

  return result
}

export default function EditPage() {
  const { id }   = useParams()
  const navigate = useNavigate()

  const [title,      setTitle]      = useState('')
  const [content,    setContent]    = useState('')
  const [images,     setImages]     = useState([])
  const [uploading,  setUploading]  = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [loading,    setLoading]    = useState(true)
  const [msg,        setMsg]        = useState('')
  const [mode,       setMode]       = useState('edit') // 'edit' | 'preview' | 'split'
  const [saved,      setSaved]      = useState(false)

  const textareaRef = useRef(null)

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

  // 自动调整 textarea 高度
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.max(ta.scrollHeight, 480) + 'px'
  }, [content])

  // Tab 键插入缩进
  const handleKeyDown = (e) => {
    if (e.key === 'Tab') {
      e.preventDefault()
      const start = e.target.selectionStart
      const end   = e.target.selectionEnd
      const newVal = content.substring(0, start) + '  ' + content.substring(end)
      setContent(newVal)
      setTimeout(() => {
        e.target.selectionStart = e.target.selectionEnd = start + 2
      }, 0)
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
      await noteApi.updateNote(id, { title, content, images })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      setMsg('保存失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return (
    <div className={styles.loading}><div className={styles.spinner} /></div>
  )

  return (
    <div className={styles.page}>

      {/* 顶部栏 */}
      <header className={styles.header}>
        <button className={styles.back} onClick={() => navigate(-1)}>
          ← 返回
        </button>

        {/* 模式切换 */}
        <div className={styles.modeSwitch}>
          <button
            className={`${styles.modeBtn} ${mode === 'edit' ? styles.modeActive : ''}`}
            onClick={() => setMode('edit')}
          >编辑</button>
          <button
            className={`${styles.modeBtn} ${mode === 'split' ? styles.modeActive : ''}`}
            onClick={() => setMode('split')}
          >分栏</button>
          <button
            className={`${styles.modeBtn} ${mode === 'preview' ? styles.modeActive : ''}`}
            onClick={() => setMode('preview')}
          >预览</button>
        </div>

        <button
          className={`${styles.btnSave} ${saved ? styles.btnSaved : ''}`}
          onClick={handleSubmit}
          disabled={submitting}
        >
          {saved ? '✓ 已保存' : submitting ? '保存中...' : '保存'}
        </button>
      </header>

      <div className={styles.body}>

        {/* 标题输入 */}
        <input
          className={styles.titleInput}
          type="text"
          placeholder="请输入标题..."
          value={title}
          onChange={e => setTitle(e.target.value)}
          maxLength={128}
        />

        <div className={styles.divider} />

        {/* 编辑器区域 */}
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
                placeholder={`开始写作...

支持 Markdown + LaTeX 语法：
# 一级标题  ## 二级标题
**粗体**  *斜体*  \`代码\`
- 列表项   > 引用

行内公式：$E = mc^2$
块级公式：
$$
\\int_{-\\infty}^{\\infty} e^{-x^2} dx = \\sqrt{\\pi}
$$`}
              />
            </div>
          )}

          {/* 分栏分割线 */}
          {mode === 'split' && <div className={styles.splitLine} />}

          {/* 预览区 */}
          {(mode === 'preview' || mode === 'split') && (
            <div
              className={styles.previewPane}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
            />
          )}
        </div>

        {/* 图片上传 */}
        <div className={styles.imageSection}>
          <div className={styles.imageSectionTitle}>
            <span>配图</span>
            <span className={styles.imageHint}>支持多张</span>
          </div>

          <label className={styles.uploadArea}>
            <input
              type="file"
              accept="image/*"
              multiple
              style={{ display: 'none' }}
              onChange={handleFile}
            />
            {uploading
              ? <span className={styles.uploadingText}>上传中...</span>
              : <span className={styles.uploadText}>
                  <span className={styles.uploadIcon}>+</span> 点击添加图片
                </span>
            }
          </label>

          {images.length > 0 && (
            <div className={styles.imageGrid}>
              {images.map((url, i) => (
                <div key={i} className={styles.imageItem}>
                  <img src={url} alt="" />
                  <button
                    className={styles.imageRemove}
                    onClick={() => removeImage(i)}
                  >✕</button>
                </div>
              ))}
            </div>
          )}
        </div>

        {msg && <div className={styles.msg}>{msg}</div>}

      </div>
    </div>
  )
}