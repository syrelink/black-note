import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { userApi, noteApi, followApi } from '../api'
import { useAuth } from '../hooks/useAuth'
import NoteCard from '../components/NoteCard'
import NoteDetail from '../components/NoteDetail'
import styles from './UserPage.module.css'

export default function UserPage() {
  const { userId }  = useParams()
  const navigate    = useNavigate()
  const { isLogin, userId: myId } = useAuth()

  const [user,       setUser]       = useState(null)
  const [notes,      setNotes]      = useState([])
  const [loading,    setLoading]    = useState(true)
  const [following,  setFollowing]  = useState(false)
  const [activeNote, setActiveNote] = useState(null)

  const isMe = String(myId) === String(userId)

  useEffect(() => {
    loadAll()
  }, [userId])

  const loadAll = async () => {
    setLoading(true)
    try {
      // 并行请求用户信息和笔记列表
      const [userRes, notesRes] = await Promise.all([
        userApi.getById(userId),
        noteApi.listByUser(userId),
      ])
      setUser(userRes.data)
      setNotes(notesRes.data || [])

      // 如果已登录且不是自己，查询关注状态
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
    try {
      await followApi.follow(userId)
      setFollowing(prev => !prev)
    } catch {}
  }

  if (loading) return (
    <div className={styles.loading}>
      <div className={styles.spinner} />
    </div>
  )

  if (!user) return (
    <div className={styles.notFound}>
      <p>用户不存在</p>
      <button onClick={() => navigate('/')}>返回首页</button>
    </div>
  )

  return (
    <div className={styles.page}>
      {/* 返回按钮 */}
      <button className={styles.back} onClick={() => navigate(-1)}>
        ← 返回
      </button>

      {/* 用户信息卡片 */}
      <div className={styles.profile}>
        <div className={styles.avatarLarge}>
          {user.avatar
            ? <img src={user.avatar} alt={user.nickname} />
            : <span>{(user.nickname || user.username)?.charAt(0)?.toUpperCase()}</span>
          }
        </div>

        <div className={styles.info}>
          <h1 className={styles.name}>
            {user.nickname || user.username}
          </h1>
          <p className={styles.username}>@{user.username}</p>
          <p className={styles.noteCount}>{notes.length} 篇笔记</p>
        </div>

        {/* 关注按钮（不显示在自己的主页上）*/}
        {isLogin && !isMe && (
          <button
            className={`${styles.followBtn} ${following ? styles.following : ''}`}
            onClick={handleFollow}
          >
            {following ? '已关注' : '+ 关注'}
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
            <NoteCard
              key={note.id}
              note={note}
              index={i}
              onClick={setActiveNote}
            />
          ))}
        </div>
      )}

      {/* 笔记详情弹窗 */}
      {activeNote && (
        <NoteDetail
          note={activeNote}
          onClose={() => setActiveNote(null)}
        />
      )}
    </div>
  )
}