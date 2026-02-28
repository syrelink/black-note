import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './hooks/useAuth'
import Home     from './pages/Home'
import UserPage from './pages/UserPage'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/"            element={<Home />} />
        <Route path="/user/:userId" element={<UserPage />} />
      </Routes>
    </AuthProvider>
  )
}