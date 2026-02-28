import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import styles from './Navbar.module.css'

export default function Navbar({ activeTab, onTabChange, onPublish, onLogin }) {
  const { nickname, avatar, isLogin, logout, userId } = useAuth()
  const navigate = useNavigate()

  return (
    <nav className={styles.nav}>
      {/* Logo */}
      <div className={styles.logo} onClick={() => navigate('/')}>
        小黑<span>书</span>
      </div>

      {/* 中间 Tab */}
      <div className={styles.tabs}>
        <button
          className={`${styles.tab} ${activeTab === 'discover' ? styles.active : ''}`}
          onClick={() => onTabChange('discover')}
        >发现</button>
        <button
          className={`${styles.tab} ${activeTab === 'follow' ? styles.active : ''}`}
          onClick={() => onTabChange('follow')}
        >关注</button>
      </div>

      {/* 右侧：用户信息区 */}
      <div className={styles.right}>
        {isLogin ? (
          // 已登录：显示头像 + 昵称，点击跳转个人主页
          <>
            <div
              className={styles.userInfo}
              onClick={() => navigate(`/user/${userId}`)}
            >
              <div className={styles.avatarWrap}>
                {avatar
                  ? <img src={avatar} alt={nickname} />
                  : <span className={styles.avatarFallback}>
                      {nickname?.charAt(0)?.toUpperCase() || '?'}
                    </span>
                }
              </div>
              <span className={styles.nickname}>{nickname}</span>
            </div>
            <button className={styles.btnSecondary} onClick={logout}>退出</button>
          </>
        ) : (
          <button className={styles.btnSecondary} onClick={onLogin}>登录</button>
        )}
        <button className={styles.btnPrimary} onClick={onPublish}>+ 发布</button>
      </div>
    </nav>
  )
}