import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './hooks/useAuth'
import Home     from './pages/Home'
import UserPage from './pages/UserPage'
import EditPage from './pages/EditPage'
import ChatPage from './pages/ChatPage'   

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/"                element={<Home />} />
        <Route path="/user/:userId"    element={<UserPage />} />
        <Route path="/note/edit/:id"   element={<EditPage />} />
        <Route path="/chat"            element={<ChatPageWrapper />} /> 
      </Routes>
    </AuthProvider>
  )
}

// 包一层，从 useAuth 取出 userId 传给 ChatPage
function ChatPageWrapper() {
  const { userId } = useAuth()
  return <ChatPage userId={userId} />
}