import styles from './ConfirmModal.module.css'

export default function ConfirmModal({ title, message, onConfirm, onCancel, loading }) {
  return (
    <div className={styles.overlay} onClick={onCancel}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <h3 className={styles.title}>{title || '确认操作'}</h3>
        <p className={styles.message}>{message || '确定要执行此操作吗？'}</p>
        <div className={styles.actions}>
          <button className={styles.cancelBtn} onClick={onCancel} disabled={loading}>
            取消
          </button>
          <button className={styles.confirmBtn} onClick={onConfirm} disabled={loading}>
            {loading ? '删除中...' : '确认删除'}
          </button>
        </div>
      </div>
    </div>
  )
}