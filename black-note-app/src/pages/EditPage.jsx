import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import rehypeSlug from 'rehype-slug'
import 'katex/dist/katex.min.css'
import 'highlight.js/styles/github.css'
import { noteApi, fileApi } from '../api'
import styles from './EditPage.module.css'

function parseOutline(content) {
  const lines = content.split('\n')
  const headings = []
  let inCode = false
  lines.forEach((line, idx) => {
    if (line.startsWith('```')) { inCode = !inCode; return }
    if (inCode) return
    const m = line.match(/^(#{1,3})\s+(.+)/)
    if (m) headings.push({ level: m[1].length, text: m[2].trim(), lineIndex: idx })
  })
  return headings
}

function MarkdownPreview({ content, className }) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex, rehypeHighlight, rehypeSlug]}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

function OutlinePanel({ outline, collapsed, onToggle, onJump }) {
  return (
    <div className={`${styles.outline} ${collapsed ? styles.outlineCollapsed : ''}`}>
      <div className={styles.outlineHeader}>
        <span className={styles.outlineTitle}>{collapsed ? '§' : '大纲'}</span>
        <button className={styles.outlineToggle} onClick={onToggle}>
          {collapsed ? '»' : '«'}
        </button>
      </div>
      {!collapsed && (
        <div className={styles.outlineList}>
          {outline.length === 0
            ? <span className={styles.outlineEmpty}>暂无标题</span>
            : outline.map((h, i) => (
                <button key={i} className={styles.outlineItem}
                  style={{ paddingLeft: `${(h.level - 1) * 14 + 10}px` }}
                  onClick={() => onJump(h)} title={h.text}
                >
                  <span className={styles.outlineDot} data-level={h.level} />
                  <span className={styles.outlineText}>{h.text}</span>
                </button>
              ))
          }
        </div>
      )}
    </div>
  )
}

export default function EditPage() {
  const { id }   = useParams()
  const navigate = useNavigate()

  const [title,            setTitle]           = useState('')
  const [content,          setContent]         = useState('')
  const [uploading,        setUploading]       = useState(false)
  const [submitting,       setSubmitting]      = useState(false)
  const [loading,          setLoading]         = useState(true)
  const [msg,              setMsg]             = useState('')
  const [mode,             setMode]            = useState('edit')
  const [saved,            setSaved]           = useState(false)
  const [outlineCollapsed, setOutlineCollapsed]= useState(false)
  const [syncScroll,       setSyncScroll]      = useState(true)

  const textareaRef = useRef(null)
  const editPaneRef = useRef(null)
  const previewRef  = useRef(null)
  const syncing     = useRef(false)

  const outline = useMemo(() => parseOutline(content), [content])

  useEffect(() => {
    noteApi.getById(id)
      .then(res => {
        const note = res.data
        setTitle(note.title || '')
        setContent(note.content || '')
      })
      .catch(() => setMsg('加载失败'))
      .finally(() => setLoading(false))
  }, [id])

  // 切换模式：重置滚动 + 修正 textarea overflow/height
  useEffect(() => {
    if (editPaneRef.current) editPaneRef.current.scrollTop = 0
    if (previewRef.current)  previewRef.current.scrollTop  = 0

    const ta = textareaRef.current
    if (!ta) return

    if (mode === 'split') {
      ta.style.overflow = 'hidden'
      ta.style.height   = 'auto'
      setTimeout(() => {
        if (textareaRef.current)
          textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px'
      }, 0)
    } else if (mode === 'edit') {
      ta.style.overflow = 'hidden'
      ta.style.height   = 'auto'
      ta.style.height   = Math.max(ta.scrollHeight, 480) + 'px'
    }
  }, [mode])

  // content 变化撑高（仅单栏编辑）
  useEffect(() => {
    if (mode !== 'edit') return
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.max(ta.scrollHeight, 480) + 'px'
  }, [content, mode])

  const handleEditScroll = useCallback(() => {
    if (!syncScroll || mode !== 'split' || syncing.current) return
    const edit = editPaneRef.current, prev = previewRef.current
    if (!edit || !prev) return
    syncing.current = true
    const ratio = edit.scrollTop / Math.max(edit.scrollHeight - edit.clientHeight, 1)
    prev.scrollTop  = ratio * Math.max(prev.scrollHeight - prev.clientHeight, 1)
    requestAnimationFrame(() => { syncing.current = false })
  }, [syncScroll, mode])

  const handlePreviewScroll = useCallback(() => {
    if (!syncScroll || mode !== 'split' || syncing.current) return
    const edit = editPaneRef.current, prev = previewRef.current
    if (!edit || !prev) return
    syncing.current = true
    const ratio = prev.scrollTop / Math.max(prev.scrollHeight - prev.clientHeight, 1)
    edit.scrollTop  = ratio * Math.max(edit.scrollHeight - edit.clientHeight, 1)
    requestAnimationFrame(() => { syncing.current = false })
  }, [syncScroll, mode])

  const handleJump = useCallback((h) => {
    const ta = textareaRef.current
    if (ta) {
      const lines = ta.value.split('\n')
      const pos = lines.slice(0, h.lineIndex).join('\n').length + (h.lineIndex > 0 ? 1 : 0)
      ta.focus()
      ta.selectionStart = ta.selectionEnd = pos
      const ep = editPaneRef.current
      if (ep) {
        const lh = parseFloat(getComputedStyle(ta).lineHeight) || 22
        ep.scrollTop = h.lineIndex * lh - 60
      }
    }
    const pv = previewRef.current
    if (pv) {
      const allH = pv.querySelectorAll('h1, h2, h3')
      const idx  = outline.findIndex(o => o.lineIndex === h.lineIndex)
      const el   = allH[idx]
      if (el) pv.scrollTop = el.offsetTop - 20
    }
  }, [outline])

  const handleKeyDown = (e) => {
    if (e.key !== 'Tab') return
    e.preventDefault()
    const s = e.target.selectionStart
    const newVal = content.substring(0, s) + '  ' + content.substring(e.target.selectionEnd)
    setContent(newVal)
    setTimeout(() => { e.target.selectionStart = e.target.selectionEnd = s + 2 }, 0)
  }

  // 上传图片并在光标处插入 markdown img 语法
  const handleImageUpload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setUploading(true)
    try {
      const url = await fileApi.upload(file).then(r => r.data)
      const ta  = textareaRef.current
      const start = ta ? ta.selectionStart : content.length
      const imgMd = `![图片](${url})`
      const newContent = content.substring(0, start) + imgMd + content.substring(start)
      setContent(newContent)
      setTimeout(() => {
        if (ta) {
          ta.selectionStart = ta.selectionEnd = start + imgMd.length
          ta.focus()
        }
      }, 0)
    } catch {
      setMsg('图片上传失败')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const handleSubmit = async () => {
    if (!title.trim())   { setMsg('标题不能为空'); return }
    if (!content.trim()) { setMsg('内容不能为空'); return }
    setSubmitting(true); setMsg('')
    try {
      await noteApi.updateNote(id, { title, content, images: [] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)  // 留在编辑页，2秒后恢复按钮
    } catch {
      setMsg('保存失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <div className={styles.loading}><div className={styles.spinner} /></div>

  const isSplit = mode === 'split'

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <button className={styles.back} onClick={() => navigate(-1)}>← 返回</button>
        <div className={styles.modeSwitch}>
          {[
            { key: 'edit',    label: '编辑' },
            { key: 'split',   label: '分栏' },
            { key: 'preview', label: '预览' },
          ].map(({ key, label }) => (
            <button key={key}
              className={`${styles.modeBtn} ${mode === key ? styles.modeActive : ''}`}
              onClick={() => setMode(key)}
            >{label}</button>
          ))}
        </div>
        <div className={styles.headerRight}>
          {isSplit && (
            <button
              className={`${styles.syncBtn} ${syncScroll ? styles.syncOn : ''}`}
              onClick={() => setSyncScroll(v => !v)}
            >
              ⇅ {syncScroll ? '同步' : '独立'}
            </button>
          )}
          <label className={styles.toolbarBtn}>
            <input
              type="file"
              accept="image/*"
              style={{ display: 'none' }}
              onChange={handleImageUpload}
            />
            {uploading ? '上传中...' : '🖼 插入图片'}
          </label>
          <button
            className={`${styles.btnSave} ${saved ? styles.btnSaved : ''}`}
            onClick={handleSubmit} disabled={submitting}
          >
            {saved ? '✓ 已保存' : submitting ? '保存中...' : '保存'}
          </button>
        </div>
      </header>

      <div className={styles.pageBody}>
        <OutlinePanel
          outline={outline}
          collapsed={outlineCollapsed}
          onToggle={() => setOutlineCollapsed(v => !v)}
          onJump={handleJump}
        />

        <div className={`${styles.body} ${isSplit ? styles.bodySplit : ''}`}>
          <input
            className={styles.titleInput}
            type="text" placeholder="请输入标题..."
            value={title} onChange={e => setTitle(e.target.value)} maxLength={128}
          />
          <div className={styles.divider} />

          <div className={`${styles.editorWrap} ${styles['mode_' + mode]}`}>

            {(mode === 'edit' || mode === 'split') && (
              <div
                ref={editPaneRef}
                className={`${styles.editPane} ${isSplit ? styles.editPaneSplit : ''}`}
                onScroll={handleEditScroll}
              >
                <textarea
                  ref={textareaRef}
                  className={styles.editor}
                  value={content}
                  onChange={e => setContent(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={`开始写作...\n\n支持 Markdown + LaTeX：\n# 一级标题\n**粗体**  *斜体*  \`代码\`\n- 列表\n> 引用\n$E=mc^2$\n\n插入图片：点击右上角"🖼 插入图片"按钮`}
                />
              </div>
            )}

            {isSplit && <div className={styles.splitLine} />}

            {(mode === 'preview' || mode === 'split') && (
              <div
                ref={previewRef}
                className={`${styles.previewWrapper} ${isSplit ? styles.previewWrapperSplit : styles.previewWrapperFull}`}
                onScroll={handlePreviewScroll}
              >
                <MarkdownPreview content={content} className={styles.previewPane} />
              </div>
            )}
          </div>

          {msg && <div className={styles.msg}>{msg}</div>}
        </div>
      </div>
    </div>
  )
}