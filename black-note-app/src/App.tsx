// src/App.tsx
import { BrowserRouter as Router, Routes, Route, Link, Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import UserListPage from './pages/UserListPage'
import LoginPage from './pages/LoginPage'
import BlogListPage from './pages/BlogListPage'
import BlogDetailPage from './pages/BlogDetailPage'
import CreateBlogPage from './pages/CreateBlogPage'
import ShopListPage from './pages/ShopListPage'

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/*" element={<ProtectedLayout />} />
      </Routes>
    </Router>
  )
}

// 受保护的布局（需要登录）
function ProtectedLayout() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('auth_token');
    setIsAuthenticated(!!token);
    setIsChecking(false);
  }, []);

  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-lg">检查登录状态...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 导航栏 */}
      <nav className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <div className="flex items-center gap-8">
              <h1 className="text-xl font-bold text-gray-900">
                📓 小黑书
              </h1>
              <div className="flex gap-6">
                <Link 
                  to="/" 
                  className="text-gray-600 hover:text-gray-900 font-medium transition-colors"
                >
                  首页
                </Link>
                <Link 
                  to="/users" 
                  className="text-gray-600 hover:text-gray-900 font-medium transition-colors"
                >
                  用户管理
                </Link>
                <Link 
                  to="/blogs" 
                  className="text-gray-600 hover:text-gray-900 font-medium transition-colors"
                >
                  笔记管理
                </Link>
                <Link 
                  to="/shops" 
                  className="text-gray-600 hover:text-gray-900 font-medium transition-colors"
                >
                  店铺管理
                </Link>
              </div>
            </div>
            
            <button
              onClick={() => {
                localStorage.removeItem('auth_token');
                window.location.href = '/login';
              }}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 transition-colors"
            >
              退出登录
            </button>
          </div>
        </div>
      </nav>

      {/* 主内容区 */}
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/users" element={<UserListPage />} />
          <Route path="/blogs" element={<BlogListPage />} />
          <Route path="/blog/:id" element={<BlogDetailPage />} />
          <Route path="/blog/create" element={<CreateBlogPage />} />
          <Route path="/shops" element={<ShopListPage />} />
        </Routes>
      </main>
    </div>
  );
}

// 首页组件
function HomePage() {
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">
          欢迎使用小黑书管理系统
        </h1>
        <p className="text-lg text-gray-600 mb-8">
          一个带有电商功能的图文笔记平台 - 基于 React + TypeScript + Tailwind CSS
        </p>
        
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mt-12">
          <Link 
            to="/users"
            className="p-6 bg-white rounded-lg shadow hover:shadow-lg transition-all hover:-translate-y-1"
          >
            <div className="text-3xl mb-3">👥</div>
            <h3 className="text-lg font-semibold mb-2">用户管理</h3>
            <p className="text-gray-600 text-sm">管理平台用户信息</p>
          </Link>
          
          <Link 
            to="/blogs"
            className="p-6 bg-white rounded-lg shadow hover:shadow-lg transition-all hover:-translate-y-1"
          >
            <div className="text-3xl mb-3">📝</div>
            <h3 className="text-lg font-semibold mb-2">笔记管理</h3>
            <p className="text-gray-600 text-sm">管理用户图文笔记</p>
          </Link>
          
          <Link 
            to="/shops"
            className="p-6 bg-white rounded-lg shadow hover:shadow-lg transition-all hover:-translate-y-1"
          >
            <div className="text-3xl mb-3">🏪</div>
            <h3 className="text-lg font-semibold mb-2">店铺管理</h3>
            <p className="text-gray-600 text-sm">管理平台商家店铺</p>
          </Link>
          
          <div className="p-6 bg-white rounded-lg shadow hover:shadow-lg transition-all hover:-translate-y-1">
            <div className="text-3xl mb-3">🎟️</div>
            <h3 className="text-lg font-semibold mb-2">优惠券管理</h3>
            <p className="text-gray-600 text-sm">管理店铺优惠活动</p>
          </div>
        </div>

        <div className="mt-12 p-6 bg-blue-50 rounded-lg">
          <h3 className="text-lg font-semibold text-gray-900 mb-2">
            🚀 技术栈
          </h3>
          <div className="flex flex-wrap justify-center gap-3 text-sm">
            <span className="px-3 py-1 bg-white rounded-full text-gray-700">React 18</span>
            <span className="px-3 py-1 bg-white rounded-full text-gray-700">TypeScript</span>
            <span className="px-3 py-1 bg-white rounded-full text-gray-700">Vite</span>
            <span className="px-3 py-1 bg-white rounded-full text-gray-700">Tailwind CSS</span>
            <span className="px-3 py-1 bg-white rounded-full text-gray-700">React Query</span>
            <span className="px-3 py-1 bg-white rounded-full text-gray-700">Orval</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export default App