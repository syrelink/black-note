import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { noteApi, followApi } from '../api'
import { useAuth } from '../hooks/useAuth'
import Navbar from '../components/Navbar'
import SearchBar from '../components/SearchBar'
import Masonry from '../components/Masonry'
import NoteDetail from '../components/NoteDetail'
import PublishModal from '../components/PublishModal'
import LoginModal from '../components/LoginModal'
import styles from './Home.module.css'

export default function Home() {
  const { isLogin , userId: myId}  = useAuth()
  const navigate     = useNavigate()

  const [tab,         setTab]         = useState('discover')
  const [notes,       setNotes]       = useState([])
  const [followUsers, setFollowUsers] = useState([])
  const [loading,     setLoading]     = useState(false)
  const [hasMore,     setHasMore]     = useState(true)
  const [keyword,     setKeyword]     = useState('')
  const [activeNote,  setActiveNote]  = useState(null)
  const [showPublish, setShowPublish] = useState(false)
  const [showLogin,   setShowLogin]   = useState(false)
  const [likeMap,     setLikeMap]     = useState({})
  const [refreshing,  setRefreshing]  = useState(false)
  const [pullDist,    setPullDist]    = useState(0)

  const discoverPageRef = useRef(1)
  const loadingRef      = useRef(false)
  const hasMoreRef      = useRef(true)
  const touchStartY     = useRef(0)
  const PULL_THRESHOLD  = 70

  // ── 加载数据 ──
  const loadNotes = useCallback(async (reset) => {
    if (loadingRef.current) return
    if (!reset && !hasMoreRef.current) return

    loadingRef.current = true
    setLoading(true)

    try {
      // 关注 Tab：拉取关注的人列表
      if (tab === 'follow' && isLogin) {
        const res = await followApi.followList(myId)
        setFollowUsers(res.data || [])
        return
      }

      // 发现 Tab：拉取笔记列表
      const page = reset ? 1 : discoverPageRef.current
      const res  = await noteApi.noteList(page, 20)
      const list = res.data || []
      const more = list.length === 20
      discoverPageRef.current = reset ? 2 : page + 1

      setNotes(prev => reset ? list : [...prev, ...list])
      setLikeMap(prev => {
        const next = { ...prev }
        list.forEach(n => {
          if (!next[n.id]) {
            next[n.id] = { liked: !!n.isLiked, count: n.likeCount || 0 }
          }
        })
        return next
      })
      setHasMore(more)
      hasMoreRef.current = more

    } catch {
      if (reset) setNotes(MOCK)
      setHasMore(false)
      hasMoreRef.current = false
    } finally {
      setLoading(false)
      loadingRef.current = false
    }
  }, [tab, isLogin])

  // 点赞处理
  const handleLike = async (noteId) => {
    if (!isLogin) return
    await noteApi.like(noteId)
    setLikeMap(prev => {
      const cur      = prev[noteId] || { liked: false, count: 0 }
      const newLiked = !cur.liked
      return {
        ...prev,
        [noteId]: { liked: newLiked, count: newLiked ? cur.count + 1 : cur.count - 1 }
      }
    })
  }

  // tab / 登录状态变化时重置
  useEffect(() => {
    discoverPageRef.current = 1
    hasMoreRef.current = true
    loadNotes(true)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, isLogin])

  // 无限滚动
  useEffect(() => {
    const handleScroll = () => {
      const distFromBottom = document.documentElement.scrollHeight - window.scrollY - window.innerHeight
      if (distFromBottom < 200) loadNotes(false)
    }
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [loadNotes])

  // 下拉刷新
  useEffect(() => {
    const handleTouchStart = (e) => {
      touchStartY.current = window.scrollY === 0 ? e.touches[0].clientY : 0
    }
    const handleTouchMove = (e) => {
      if (!touchStartY.current) return
      const dist = e.touches[0].clientY - touchStartY.current
      if (dist > 0 && dist < 120) setPullDist(dist)
    }
    const handleTouchEnd = async () => {
      if (pullDist >= PULL_THRESHOLD) {
        setRefreshing(true)
        discoverPageRef.current = 1
        hasMoreRef.current = true
        await loadNotes(true)
        setRefreshing(false)
      }
      setPullDist(0)
      touchStartY.current = 0
    }
    window.addEventListener('touchstart', handleTouchStart, { passive: true })
    window.addEventListener('touchmove',  handleTouchMove,  { passive: true })
    window.addEventListener('touchend',   handleTouchEnd)
    return () => {
      window.removeEventListener('touchstart', handleTouchStart)
      window.removeEventListener('touchmove',  handleTouchMove)
      window.removeEventListener('touchend',   handleTouchEnd)
    }
  }, [loadNotes, pullDist])

  const handleTabChange = (t) => {
    if (t === 'follow' && !isLogin) { setShowLogin(true); return }
    setTab(t)
  }

  const displayNotes = keyword
    ? notes.filter(n => n.title?.includes(keyword) || n.content?.includes(keyword))
    : notes

  const pullIndicatorStyle = {
    transform:  `translateY(${Math.min(pullDist, PULL_THRESHOLD) - 40}px)`,
    opacity:    pullDist / PULL_THRESHOLD,
    transition: pullDist === 0 ? 'all .3s ease' : 'none',
  }

  return (
    <>
      <Navbar
        activeTab={tab}
        onTabChange={handleTabChange}
        onPublish={() => isLogin ? setShowPublish(true) : setShowLogin(true)}
        onLogin={() => setShowLogin(true)}
      />

      <SearchBar
        onSearch={setKeyword}
        onTagChange={() => {
          discoverPageRef.current = 1
          hasMoreRef.current = true
          loadNotes(true)
        }}
      />

      {/* 下拉刷新指示器 */}
      <div className={styles.pullIndicator} style={pullIndicatorStyle}>
        {refreshing
          ? <div className={styles.refreshSpinner} />
          : <span>{pullDist >= PULL_THRESHOLD ? '松开刷新' : '下拉刷新'}</span>
        }
      </div>

      <main className={styles.main}>

        {/* ── 关注 Tab：展示关注的人列表 ── */}
        {tab === 'follow' && !loading && (
          followUsers.length === 0 ? (
            <div className={styles.empty}>
              <div className={styles.emptyIcon}>👥</div>
              <p>还没有关注任何人，去发现更多吧</p>
            </div>
          ) : (
            <div className={styles.followList}>
              {followUsers.map(user => (
                <div
                  key={user.id}
                  className={styles.followItem}
                  onClick={() => navigate(`/user/${user.id}`)}
                >
                  <div className={styles.followAvatar}>
                    {user.avatar
                      ? <img src={user.avatar} alt={user.nickname} />
                      : <span>{(user.nickname || user.username)?.charAt(0)}</span>
                    }
                  </div>
                  <span className={styles.followName}>
                    {user.nickname || user.username}
                  </span>
                </div>
              ))}
            </div>
          )
        )}

        {/* ── 发现 Tab：笔记瀑布流 ── */}
        {tab === 'discover' && displayNotes.length > 0 && (
          <Masonry
            notes={displayNotes}
            onCardClick={setActiveNote}
            onLike={handleLike}
            likeMap={likeMap}
          />
        )}

        {tab === 'discover' && !loading && displayNotes.length === 0 && (
          <div className={styles.empty}>
            <div className={styles.emptyIcon}>📖</div>
            <p>暂无笔记</p>
          </div>
        )}

        {/* 加载中 */}
        {loading && !refreshing && (
          <div className={styles.bottomLoading}>
            <div className={styles.spinner} />
            <span>加载中...</span>
          </div>
        )}

        {/* 没有更多 */}
        {tab === 'discover' && !hasMore && !loading && notes.length > 0 && (
          <div className={styles.noMore}>— 已经到底了 —</div>
        )}

      </main>

      {activeNote && (
        <NoteDetail
          note={activeNote}
          onClose={() => setActiveNote(null)}
          onLike={handleLike}
          likeMap={likeMap}
        />
      )}

      {showPublish && (
        <PublishModal
          onClose={() => setShowPublish(false)}
          onSuccess={() => {
            discoverPageRef.current = 1
            hasMoreRef.current = true
            loadNotes(true)
          }}
        />
      )}

      {showLogin && (
        <LoginModal onClose={() => setShowLogin(false)} />
      )}
    </>
  )
}