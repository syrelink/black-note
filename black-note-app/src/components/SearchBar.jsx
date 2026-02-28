import { useState } from 'react'
import styles from './SearchBar.module.css'

const TAGS = ['全部', '摄影', '旅行', '美食', '生活', '科技', '读书', '音乐']

export default function SearchBar({ onSearch, onTagChange }) {
  const [activeTag, setActiveTag] = useState('全部')

  const handleTag = (tag) => {
    setActiveTag(tag)
    onTagChange(tag === '全部' ? '' : tag)
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.searchBox}>
        <span className={styles.icon}>⌕</span>
        <input
          type="text"
          placeholder="搜索笔记..."
          onChange={e => onSearch(e.target.value)}
        />
      </div>
      <div className={styles.tags}>
        {TAGS.map(tag => (
          <button
            key={tag}
            className={`${styles.tag} ${activeTag === tag ? styles.active : ''}`}
            onClick={() => handleTag(tag)}
          >
            {tag}
          </button>
        ))}
      </div>
    </div>
  )
}
