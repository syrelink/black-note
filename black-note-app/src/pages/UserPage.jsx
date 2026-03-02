import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { userApi, noteApi, followApi, fileApi } from '../api'
import { useAuth } from '../hooks/useAuth'
import NoteCard from '../components/NoteCard'
import NoteDetail from '../components/NoteDetail'
import styles from './UserPage.module.css'

export default function UserPage() {
  const { userId }  = useParams()
  const navigate    = useNavigate()
  const { isLogin, userId: myId, updateUser } = useAuth()

  const [user,       setUser]       = useState(null)
  const [notes,      setNotes]      = useState([])
  const [loading,    setLoading]    = useState(true)
  const [following,  setFollowing]  = useState(false)
  const [activeNote, setActiveNote] = useState(null)
  const [followLoad, setFollowLoad] = useState(false)

  // 编辑弹窗状态
  const [showEdit,   setShowEdit]   = useState(false)
  const [editNick,   setEditNick]   = useState('')
  const [editAvatar, setEditAvatar] = useState('')
  const [uploading,  setUploading]  = useState(false)
  const [saving,     setSaving]     = useState(false)
  const [editMsg,    setEditMsg]    = useState('')

  const isMe = String(myId) === String(userId)

  useEffect(() => { loadAll() }, [userId])

  const loadAll = async () => {
    setLoading(true)
    try {
      const [userRes, notesRes] = await Promise.all([
        userApi.getById(userId),
        noteApi.listByUser(userId),
      ])
      setUser(userRes.data)
      setNotes(notesRes.data || [])
      if (isLogin && !isMe) {
        const followRes = await followApi.isFollow(userId)
        setFollowing(!!followRes.data)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const handleFollow = async () => {
    if (!isLogin) return
    setFollowLoad(true)
    try {
      await followApi.follow(userId)
      setFollowing(prev => !prev)
    } catch {} finally {
      setFollowLoad(false)
    }
  }

  const openEdit = () => {
    setEditNick(user.nickname || '')
    setEditAvatar(user.avatar || '')
    setEditMsg('')
    setShowEdit(true)
  }

  const handleAvatarFile = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setUploading(true)
    try {
      const res = await fileApi.upload(file)
      setEditAvatar(res.data)
    } catch {
      setEditMsg('头像上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handleSave = async () => {
    await userApi.updateMe({ nickname: editNick, avatar: editAvatar })
    // 同时更新全局状态
    updateUser({ nickname: editNick, avatar: editAvatar })
    setUser(prev => ({ ...prev, nickname: editNick, avatar: editAvatar }))
    setShowEdit(false)
  }

  if (loading) return (
    <div className={styles.loading}><div className={styles.spinner} /></div>
  )

  if (!user) return (
    <div className={styles.notFound}>
      <p>用户不存在</p>
      <button onClick={() => navigate('/')}>返回首页</button>
    </div>
  )

  return (
    <div className={styles.page}>

      <button className={styles.back} onClick={() => navigate(-1)}>← 返回</button>

      {/* 用户信息卡 */}
      <div className={styles.profile}>
        <div className={styles.avatarLarge}>
          {user.avatar
            ? <img src={user.avatar} alt={user.nickname} />
            : <span>{(user.nickname || user.username)?.charAt(0)?.toUpperCase()}</span>
          }
        </div>

        <div className={styles.info}>
          <h1 className={styles.name}>{user.nickname || user.username}</h1>
          <p className={styles.username}>@{user.username}</p>
          <p className={styles.noteCount}>{notes.length} 篇笔记</p>
        </div>

        {isMe ? (
          <button className={styles.editProfileBtn} onClick={openEdit}>编辑资料</button>
        ) : isLogin && (
          <button
            className={`${styles.followBtn} ${following ? styles.following : ''}`}
            onClick={handleFollow}
            disabled={followLoad}
          >
            {followLoad ? '...' : following ? '已关注' : '+ 关注'}
          </button>
        )}
      </div>

      {/* 笔记列表 */}
      {notes.length === 0 ? (
        <div className={styles.empty}>
          <div className={styles.emptyIcon}>📝</div>
          <p>{isMe ? '还没有发布笔记，去发布第一篇吧' : '这个人还没有发布笔记'}</p>
        </div>
      ) : (
        <div className={styles.grid}>
          {notes.map((note, i) => (
            <NoteCard key={note.id} note={note} index={i} onClick={setActiveNote} />
          ))}
        </div>
      )}

      {activeNote && (
        <NoteDetail note={activeNote} onClose={() => setActiveNote(null)}
        onLike={() => {}}
        likeMap={{}}
        onDeleted={() => {
          setNotes(prev => prev.filter(n => n.id !== activeNote.id))
          setActiveNote(null)
        }}
        />
      )}

      {/* 编辑资料弹窗 */}
      {showEdit && (
        <div className={styles.editOverlay} onClick={e => e.target === e.currentTarget && setShowEdit(false)}>
          <div className={styles.editModal}>

            <div className={styles.editHeader}>
              <h2>编辑资料</h2>
              <button className={styles.editClose} onClick={() => setShowEdit(false)}>✕</button>
            </div>

            {/* 头像预览 + 上传 */}
            <div className={styles.editAvatarRow}>
              <div className={styles.editAvatarPreview}>
                {editAvatar
                  ? <img src={editAvatar} alt="头像" />
                  : <span>{editNick?.charAt(0)?.toUpperCase() || '?'}</span>
                }
              </div>
              <label className={styles.uploadAvatarBtn}>
                <input type="file" accept="image/*" style={{ display: 'none' }} onChange={handleAvatarFile} />
                {uploading ? '上传中...' : '更换头像'}
              </label>
            </div>

            {/* 昵称 */}
            <div className={styles.editField}>
              <label>昵称</label>
              <input
                type="text"
                value={editNick}
                onChange={e => setEditNick(e.target.value)}
                maxLength={32}
                placeholder="输入昵称..."
              />
            </div>

            {editMsg && <div className={styles.editMsg}>{editMsg}</div>}

            <div className={styles.editActions}>
              <button className={styles.editCancel} onClick={() => setShowEdit(false)}>取消</button>
              <button className={styles.editSave} onClick={handleSave} disabled={saving}>
                {saving ? '保存中...' : '保存'}
              </button>
            </div>

          </div>
        </div>
      )}

    </div>
  )
}