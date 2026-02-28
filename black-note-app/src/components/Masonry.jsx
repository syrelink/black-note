import NoteCard from './NoteCard'
import styles from './Masonry.module.css'

export default function Masonry({ notes, onCardClick }) {
  if (!notes || notes.length === 0) return null

  return (
    <div className={styles.grid}>
      {notes.map((note, i) => (
        <NoteCard
          key={note.id}
          note={note}
          index={i}
          onClick={onCardClick}
        />
      ))}
    </div>
  )
}
