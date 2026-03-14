import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import styles from './Navbar.module.css'

export default function Navbar({ activeTab, onTabChange, onPublish, onLogin }) {
  const { userInfo, isLogin, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <>
      {/* 顶部栏 */}
      <nav className={styles.nav}>
        <div className={styles.logo} onClick={() => navigate('/')}>
          小黑<span>书</span>
        </div>

        <div className={styles.right}>
          {isLogin ? (
            <>
              <div className={styles.userInfo} onClick={() => navigate(`/user/${userInfo?.id}`)}>
                <div className={styles.avatarWrap}>
                  {userInfo?.avatar
                    ? <img src={userInfo.avatar} alt={userInfo.nickname} />
                    : <span className={styles.avatarFallback}>
                        {userInfo?.nickname?.charAt(0)?.toUpperCase() || '?'}
                      </span>
                  }
                </div>
                <span className={styles.nickname}>{userInfo?.nickname || userInfo?.username}</span>
              </div>
              <button className={styles.btnSecondary} onClick={logout}>退出</button>
            </>
          ) : (
            <button className={styles.btnSecondary} onClick={onLogin}>登录</button>
          )}
          <button className={styles.btnPrimary} onClick={onPublish}>+ 发布</button>
        </div>
      </nav>

      {/* 桌面端：顶部 Tab */}
      <div className={styles.desktopTabs}>
        <button
          className={`${styles.tab} ${activeTab === 'discover' ? styles.active : ''}`}
          onClick={() => onTabChange('discover')}
        >发现</button>
        <button
          className={`${styles.tab} ${activeTab === 'rover' ? styles.active : ''}`}
          onClick={() => onTabChange('rover')}
        >
          ✨ Rover
        </button>
        <button
          className={`${styles.tab} ${activeTab === 'follow' ? styles.active : ''}`}
          onClick={() => onTabChange('follow')}
        >关注</button>
      </div>

      {/* 手机端：底部 Tab 栏 */}
      <div className={styles.bottomBar}>
        <button
          className={`${styles.bottomTab} ${activeTab === 'discover' ? styles.bottomActive : ''}`}
          onClick={() => onTabChange('discover')}
        >
          <span className={styles.bottomIcon}>🔍</span>
          <span className={styles.bottomLabel}>发现</span>
        </button>

        <button
          className={`${styles.bottomTab} ${activeTab === 'rover' ? styles.bottomActive : ''}`}
          onClick={() => onTabChange('rover')}
        >
          <span className={styles.bottomIcon}>✨</span>
          <span className={styles.bottomLabel}>Rover</span>
        </button>

        <button className={styles.bottomPublish} onClick={onPublish}>
          <span>+</span>
        </button>

        <button
          className={`${styles.bottomTab} ${activeTab === 'follow' ? styles.bottomActive : ''}`}
          onClick={() => onTabChange('follow')}
        >
          <span className={styles.bottomIcon}>👥</span>
          <span className={styles.bottomLabel}>关注</span>
        </button>
      </div>
    </>
  )
}