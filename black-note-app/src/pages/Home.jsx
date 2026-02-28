import { useState, useEffect, useCallback, useRef } from 'react'
import { noteApi, feedApi } from '../api'
import { useAuth } from '../hooks/useAuth'
import Navbar from '../components/Navbar'
import SearchBar from '../components/SearchBar'
import Masonry from '../components/Masonry'
import NoteDetail from '../components/NoteDetail'
import PublishModal from '../components/PublishModal'
import LoginModal from '../components/LoginModal'
import styles from './Home.module.css'

const MOCK = [
  { id:1, title:'清晨的第一杯手冲', content:'坐在窗边，看着晨光一点点铺开，咖啡的香气慢慢弥散，这是一天中最好的时刻。', likeCount:128, authorName:'咖啡爱好者' },
  { id:2, title:'东京雨天街拍记录', content:'用胶片记录涩谷路口雨后的人群，每一把伞都是一个故事，城市有自己的节奏。', likeCount:342, authorName:'旅行摄影师' },
  { id:3, title:'深夜读完了这本书', content:'《百年孤独》终于读完，马尔克斯构建的马孔多让人沉迷，结尾让我沉默了很久。', likeCount:215, authorName:'书虫小鱼' },
  { id:4, title:'自制抹茶蛋糕第三次尝试', content:'这次终于没有塌陷！关键是蛋白打发程度和烤箱温度，记录一下配方以防忘记。', likeCount:89, authorName:'烘焙新手' },
  { id:5, title:'骑行川藏线第14天', content:'今日海拔4800米，风很大，视野极好。远处的雪山在云间若隐若现，值得所有的疲惫。', likeCount:567, authorName:'骑行者老陈' },
  { id:6, title:'Redis缓存设计实战', content:'记录一次高并发场景下的缓存优化，从穿透到击穿，踩了不少坑，整理成文章。', likeCount:43, authorName:'后端程序员' },
  { id:7, title:'北京初雪', content:'今年第一场雪来得迟，清晨推开窗，白茫茫一片，胡同里安静得很，像是城市按了暂停键。', likeCount:198, authorName:'北漂小张' },
  { id:8, title:'30天冥想打卡完成', content:'从最初的坐立不安到现在能静坐20分钟，这一个月专注力明显提升，推荐给大家。', likeCount:76, authorName:'慢生活倡导者' },
]

export default function Home() {
  const { isLogin } = useAuth()

  const [tab,         setTab]         = useState('discover')
  const [notes,       setNotes]       = useState([])
  const [loading,     setLoading]     = useState(false)
  const [hasMore,     setHasMore]     = useState(true)
  const [keyword,     setKeyword]     = useState('')
  const [activeNote,  setActiveNote]  = useState(null)
  const [showPublish, setShowPublish] = useState(false)
  const [showLogin,   setShowLogin]   = useState(false)

  // 下拉刷新状态
  const [refreshing,  setRefreshing]  = useState(false)
  const [pullDist,    setPullDist]    = useState(0)  // 下拉距离

  const discoverPageRef = useRef(1)
  const lastTsRef       = useRef(0)
  const loadingRef      = useRef(false)   // 防止重复请求
  const hasMoreRef      = useRef(true)    // 同步hasMore给scroll监听

  // 下拉刷新的触摸记录
  const touchStartY = useRef(0)
  const PULL_THRESHOLD = 70  // 下拉超过70px触发刷新

  // ── 加载笔记 ──
  const loadNotes = useCallback(async (reset) => {
    if (loadingRef.current) return       // 防止重复请求
    if (!reset && !hasMoreRef.current) return  // 没有更多数据了

    loadingRef.current = true
    setLoading(true)

    try {
      let list = [], more = false

      if (tab === 'follow' && isLogin) {
        const ts = reset ? 0 : lastTsRef.current
        const res = await feedApi.getFeed(ts, 20)
        list = res.data?.list    || []
        more = res.data?.hasMore || false
        lastTsRef.current = res.data?.nextTimestamp || 0

      } else {
        const page = reset ? 1 : discoverPageRef.current
        const res  = await noteApi.noteList(page, 20)
        list = res.data || []
        more = list.length === 20
        discoverPageRef.current = reset ? 2 : page + 1
      }

      setNotes(prev => reset ? list : [...prev, ...list])
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

  // tab / 登录状态变化时重置
  useEffect(() => {
    lastTsRef.current = 0
    discoverPageRef.current = 1
    hasMoreRef.current = true
    loadNotes(true)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, isLogin])

  // ── 无限滚动：监听滚动到底部 ──
  useEffect(() => {
    const handleScroll = () => {
      // 距离底部还有200px时提前加载，体验更流畅
      const distFromBottom = document.documentElement.scrollHeight
        - window.scrollY
        - window.innerHeight

      if (distFromBottom < 200) {
        loadNotes(false)
      }
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [loadNotes])

  // ── 下拉刷新：触摸事件 ──
  useEffect(() => {
    const handleTouchStart = (e) => {
      // 只有在页面顶部才允许触发下拉
      if (window.scrollY === 0) {
        touchStartY.current = e.touches[0].clientY
      } else {
        touchStartY.current = 0
      }
    }

    const handleTouchMove = (e) => {
      if (!touchStartY.current) return
      const dist = e.touches[0].clientY - touchStartY.current
      if (dist > 0 && dist < 120) {
        setPullDist(dist)
      }
    }

    const handleTouchEnd = async () => {
      if (pullDist >= PULL_THRESHOLD) {
        setRefreshing(true)
        lastTsRef.current = 0
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

  // 下拉刷新指示器的样式（跟随手指移动）
  const pullIndicatorStyle = {
    transform: `translateY(${Math.min(pullDist, PULL_THRESHOLD) - 40}px)`,
    opacity: pullDist / PULL_THRESHOLD,
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
          lastTsRef.current = 0
          discoverPageRef.current = 1
          hasMoreRef.current = true
          loadNotes(true)
        }}
      />

      {/* 下拉刷新指示器 */}
      <div className={styles.pullIndicator} style={pullIndicatorStyle}>
        {refreshing ? (
          <div className={styles.refreshSpinner} />
        ) : (
          <span>{pullDist >= PULL_THRESHOLD ? '松开刷新' : '下拉刷新'}</span>
        )}
      </div>

      <main className={styles.main}>

        {displayNotes.length > 0 && (
          <Masonry notes={displayNotes} onCardClick={setActiveNote} />
        )}

        {!loading && displayNotes.length === 0 && (
          <div className={styles.empty}>
            <div className={styles.emptyIcon}>📖</div>
            <p>{tab === 'follow' ? '还没有关注的人，去发现更多吧' : '暂无笔记'}</p>
          </div>
        )}

        {/* 底部加载状态 */}
        {loading && !refreshing && (
          <div className={styles.bottomLoading}>
            <div className={styles.spinner} />
            <span>加载中...</span>
          </div>
        )}

        {/* 没有更多了 */}
        {!hasMore && !loading && notes.length > 0 && (
          <div className={styles.noMore}>— 已经到底了 —</div>
        )}

      </main>

      {activeNote && (
        <NoteDetail note={activeNote} onClose={() => setActiveNote(null)} />
      )}

      {showPublish && (
        <PublishModal
          onClose={() => setShowPublish(false)}
          onSuccess={() => {
            discoverPageRef.current = 1
            lastTsRef.current = 0
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
