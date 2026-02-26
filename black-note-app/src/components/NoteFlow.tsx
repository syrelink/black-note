import React, { useState, useEffect, type MouseEvent, type KeyboardEvent } from 'react';
import { Search, Plus, Heart, MessageCircle, Hash, X, Send, User as UserIcon, TrendingUp } from 'lucide-react';

// --- 类型定义 ---

interface User {
  id: number;
  nickName?: string;
  phone?: string;
  icon?: string;
}

interface Blog {
  id: number;
  title: string;
  content: string;
  images?: string;
  shopId?: number | null;
  name?: string; // 发布者昵称
  icon?: string; // 发布者头像
  createTime?: string;
  liked?: number; // 点赞数
  comments?: number; // 评论数
  isLike?: boolean; // 当前用户是否点赞
}

interface Comment {
  id: number;
  userName?: string;
  content: string;
  createTime?: string;
  icon?: string;
  parentId?: number;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  errorMsg?: string;
}

interface PageResult<T> {
  records: T[];
  total: number;
  size: number;
  current: number;
}

const NoteFlow: React.FC = () => {
  const API_BASE = 'http://localhost:8080';
  
  // --- State 定义 ---
  const [user, setUser] = useState<User | null>(null);
  const [blogs, setBlogs] = useState<Blog[]>([]);
  const [hotBlogs, setHotBlogs] = useState<Blog[]>([]);
  const [selectedBlog, setSelectedBlog] = useState<Blog | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'hot' | 'follow'>('hot');
  const [isCreating, setIsCreating] = useState<boolean>(false);
  const [isLogin, setIsLogin] = useState<boolean>(false);
  const [currentPage, setCurrentPage] = useState<number>(1);
  
  // 登录表单 State
  const [phone, setPhone] = useState<string>('');
  const [code, setCode] = useState<string>('');
  const [sendingCode, setSendingCode] = useState<boolean>(false);
  
  // 创建笔记表单 State
  const [newBlog, setNewBlog] = useState<{
    title: string;
    content: string;
    images: string;
    shopId: number | null;
  }>({
    title: '',
    content: '',
    images: '',
    shopId: null
  });

  // 评论相关 State
  const [comments, setComments] = useState<Comment[]>([]);
  const [newComment, setNewComment] = useState<string>('');
  const [commentPage, setCommentPage] = useState<number>(1);

  // --- Effect Hooks ---

  useEffect(() => {
    checkLoginStatus();
  }, []);

  useEffect(() => {
    if (activeTab === 'hot') {
      fetchHotBlogs();
    } else if (activeTab === 'follow') {
      fetchFollowBlogs();
    }
  }, [activeTab, currentPage]);

  // --- API Methods ---

  const checkLoginStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/user/me`, { credentials: 'include' });
      const data: ApiResponse<User> = await res.json();
      if (data.success) {
        setUser(data.data);
      }
    } catch (error) {
      console.log('未登录');
    }
  };

  const sendCode = async () => {
    if (!phone || !/^1[3-9]\d{9}$/.test(phone)) {
      alert('请输入正确的手机号');
      return;
    }
    setSendingCode(true);
    try {
      const res = await fetch(`${API_BASE}/user/code?phone=${phone}`, { method: 'POST' });
      const data: ApiResponse<null> = await res.json();
      if (data.success) {
        alert('验证码已发送！（开发环境请查看后端控制台）');
      } else {
        alert(data.errorMsg || '发送失败');
      }
    } catch (error: any) {
      alert('发送失败：' + error.message);
    } finally {
      setSendingCode(false);
    }
  };

  const login = async () => {
    try {
      const res = await fetch(`${API_BASE}/user/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ phone, code })
      });
      const data: ApiResponse<User> = await res.json();
      if (data.success) {
        setUser(data.data);
        setIsLogin(false);
        alert('登录成功！');
      } else {
        alert(data.errorMsg || '登录失败');
      }
    } catch (error: any) {
      alert('登录失败：' + error.message);
    }
  };

  const fetchHotBlogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/blog/hot?current=${currentPage}`, { credentials: 'include' });
      const data: ApiResponse<PageResult<Blog> | Blog[]> = await res.json();
      if (data.success) {
        // 兼容处理：后端可能返回分页对象或直接数组
        if (Array.isArray(data.data)) {
            setHotBlogs(data.data);
        } else {
            setHotBlogs(data.data.records);
        }
      }
    } catch (error) {
      console.error('获取热门笔记失败:', error);
    }
  };

  const fetchFollowBlogs = async () => {
    try {
      // 注意：这里的 API 路径和参数根据你的实际后端调整
      const res = await fetch(`${API_BASE}/blog/of/follow?lastId=0&offset=0`, { credentials: 'include' });
      const data: ApiResponse<{ list: Blog[] }> = await res.json();
      if (data.success) {
        setBlogs(data.data.list || []);
      }
    } catch (error) {
      console.error('获取关注笔记失败:', error);
    }
  };

  const fetchBlogDetail = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/blog/${id}`, { credentials: 'include' });
      const data: ApiResponse<Blog> = await res.json();
      if (data.success) {
        setSelectedBlog(data.data);
        fetchComments(id);
      }
    } catch (error) {
      console.error('获取笔记详情失败:', error);
    }
  };

  const fetchComments = async (blogId: number) => {
    try {
      const res = await fetch(`${API_BASE}/blog/${blogId}/comments?current=${commentPage}`, { credentials: 'include' });
      const data: ApiResponse<PageResult<Comment>> = await res.json();
      if (data.success) {
        setComments(data.data.records || []);
      }
    } catch (error) {
      console.error('获取评论失败:', error);
    }
  };

  const likeBlog = async (id: number, e?: MouseEvent) => {
    e?.stopPropagation();
    if (!user) {
      setIsLogin(true);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/blog/like/${id}`, {
        method: 'PUT',
        credentials: 'include'
      });
      const data: ApiResponse<any> = await res.json();
      if (data.success) {
        if (activeTab === 'hot') {
          fetchHotBlogs();
        } else {
          fetchFollowBlogs();
        }
        if (selectedBlog && selectedBlog.id === id) {
          fetchBlogDetail(id);
        }
      }
    } catch (error) {
      console.error('点赞失败:', error);
    }
  };

  const publishBlog = async () => {
    if (!newBlog.title || !newBlog.content) {
      alert('请填写标题和内容');
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/blog`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(newBlog)
      });
      const data: ApiResponse<any> = await res.json();
      if (data.success) {
        alert('发布成功！');
        setIsCreating(false);
        setNewBlog({ title: '', content: '', images: '', shopId: null });
        fetchHotBlogs();
      } else {
        alert(data.errorMsg || '发布失败');
      }
    } catch (error: any) {
      alert('发布失败：' + error.message);
    }
  };

  const postComment = async () => {
    if (!newComment.trim() || !selectedBlog) return;
    try {
      const res = await fetch(`${API_BASE}/blog/${selectedBlog.id}/comment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          content: newComment,
          parentId: 0
        })
      });
      const data: ApiResponse<any> = await res.json();
      if (data.success) {
        setNewComment('');
        fetchComments(selectedBlog.id);
      }
    } catch (error) {
      console.error('评论失败:', error);
    }
  };

  // --- Rendering Helpers ---

  const displayBlogs = activeTab === 'hot' ? hotBlogs : blogs;
  const filteredBlogs = searchTerm 
    ? displayBlogs.filter(blog => 
        blog.title?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        blog.content?.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : displayBlogs;

  // TypeScript 中，onError 事件处理需要指定类型
  const handleImageError = (e: React.SyntheticEvent<HTMLImageElement, Event>) => {
    e.currentTarget.style.display = 'none';
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-50 via-pink-50 to-blue-50">
      {/* 顶部导航栏 */}
      <nav className="sticky top-0 z-40 bg-white/80 backdrop-blur-lg border-b border-gray-200/50 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center space-x-2">
              <div className="w-10 h-10 bg-gradient-to-br from-purple-500 to-pink-500 rounded-xl flex items-center justify-center shadow-lg">
                <Hash className="w-6 h-6 text-white" />
              </div>
              <span className="text-2xl font-bold bg-gradient-to-r from-purple-600 to-pink-600 bg-clip-text text-transparent">
                小黑书
              </span>
            </div>

            <div className="flex-1 max-w-xl mx-8">
              <div className="relative">
                <Search className="absolute left-4 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="text"
                  placeholder="搜索笔记内容..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full pl-12 pr-4 py-2.5 rounded-full bg-gray-100 border-2 border-transparent focus:border-purple-300 focus:bg-white transition-all outline-none"
                />
              </div>
            </div>

            {user ? (
              <div className="flex items-center space-x-4">
                <button
                  onClick={() => setIsCreating(true)}
                  className="flex items-center space-x-2 px-6 py-2.5 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-full hover:shadow-lg transition-all duration-300 hover:scale-105"
                >
                  <Plus className="w-5 h-5" />
                  <span className="font-medium">发布</span>
                </button>
                <div className="flex items-center space-x-2 px-4 py-2 bg-gray-100 rounded-full">
                  <UserIcon className="w-5 h-5 text-gray-600" />
                  <span className="text-sm font-medium text-gray-700">{user.nickName || user.phone}</span>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setIsLogin(true)}
                className="px-6 py-2.5 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-full hover:shadow-lg transition-all"
              >
                登录
              </button>
            )}
          </div>
        </div>
      </nav>

      {/* 标签导航 */}
      <div className="bg-white/60 backdrop-blur-sm border-b border-gray-200/50 sticky top-16 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex space-x-2 py-3">
            <button
              onClick={() => setActiveTab('hot')}
              className={`flex items-center space-x-2 px-4 py-2 rounded-full transition-all ${
                activeTab === 'hot'
                  ? 'bg-gradient-to-r from-purple-500 to-pink-500 text-white shadow-md'
                  : 'bg-white text-gray-600 hover:bg-gray-100'
              }`}
            >
              <TrendingUp className="w-4 h-4" />
              <span>热门</span>
            </button>
            <button
              onClick={() => setActiveTab('follow')}
              className={`flex items-center space-x-2 px-4 py-2 rounded-full transition-all ${
                activeTab === 'follow'
                  ? 'bg-gradient-to-r from-purple-500 to-pink-500 text-white shadow-md'
                  : 'bg-white text-gray-600 hover:bg-gray-100'
              }`}
            >
              <Heart className="w-4 h-4" />
              <span>关注</span>
            </button>
          </div>
        </div>
      </div>

      {/* 瀑布流笔记卡片 */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {filteredBlogs.length === 0 ? (
          <div className="text-center py-20">
            <div className="text-6xl mb-4">📝</div>
            <p className="text-gray-500 text-lg">
              {activeTab === 'follow' && !user 
                ? '登录后查看关注的笔记' 
                : '暂无笔记'}
            </p>
          </div>
        ) : (
          <div className="columns-1 md:columns-2 lg:columns-3 gap-6 space-y-6">
            {filteredBlogs.map((blog) => (
              <div
                key={blog.id}
                onClick={() => fetchBlogDetail(blog.id)}
                className="break-inside-avoid bg-white rounded-2xl overflow-hidden shadow-md hover:shadow-2xl transition-all duration-300 cursor-pointer group"
              >
                {blog.images && (
                  <div className="relative overflow-hidden">
                    <img
                      src={blog.images.split(',')[0]}
                      alt={blog.title}
                      className="w-full h-auto object-cover group-hover:scale-110 transition-transform duration-500"
                      onError={handleImageError}
                    />
                    <button
                      onClick={(e) => likeBlog(blog.id, e)}
                      className={`absolute top-3 right-3 p-2 rounded-full backdrop-blur-sm transition-all ${
                        blog.isLike
                          ? 'bg-red-500 text-white'
                          : 'bg-white/80 text-gray-700 hover:bg-red-500 hover:text-white'
                      }`}
                    >
                      <Heart className="w-4 h-4" fill={blog.isLike ? 'currentColor' : 'none'} />
                    </button>
                  </div>
                )}

                <div className="p-5">
                  <h3 className="text-xl font-bold text-gray-800 mb-2 line-clamp-2">
                    {blog.title}
                  </h3>
                  <p className="text-gray-600 text-sm line-clamp-3 mb-4">
                    {blog.content}
                  </p>

                  <div className="flex items-center justify-between pt-4 border-t border-gray-100">
                    <div className="flex items-center space-x-2">
                      <div className="w-8 h-8 bg-gradient-to-br from-purple-400 to-pink-400 rounded-full flex items-center justify-center text-white text-xs font-bold">
                        {blog.name?.[0] || blog.icon || 'U'}
                      </div>
                      <div>
                        <div className="text-sm font-medium text-gray-800">{blog.name || '用户'}</div>
                        <div className="text-xs text-gray-500">
                          {blog.createTime ? new Date(blog.createTime).toLocaleDateString() : ''}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center space-x-3 text-sm text-gray-500">
                      <div className="flex items-center space-x-1">
                        <Heart className="w-4 h-4" />
                        <span>{blog.liked || 0}</span>
                      </div>
                      <div className="flex items-center space-x-1">
                        <MessageCircle className="w-4 h-4" />
                        <span>{blog.comments || 0}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* 笔记详情弹窗 */}
      {selectedBlog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-3xl max-w-4xl w-full max-h-[90vh] overflow-y-auto shadow-2xl">
            <button
              onClick={() => setSelectedBlog(null)}
              className="sticky top-4 right-4 float-right p-2 bg-white rounded-full shadow-lg hover:bg-gray-100 transition-all z-10"
            >
              <X className="w-6 h-6" />
            </button>

            {selectedBlog.images && (
              <img
                src={selectedBlog.images.split(',')[0]}
                alt={selectedBlog.title}
                className="w-full h-96 object-cover rounded-t-3xl"
                onError={handleImageError}
              />
            )}

            <div className="p-8">
              <h1 className="text-4xl font-bold text-gray-800 mb-4">{selectedBlog.title}</h1>

              <div className="flex items-center justify-between mb-6 pb-6 border-b border-gray-200">
                <div className="flex items-center space-x-3">
                  <div className="w-12 h-12 bg-gradient-to-br from-purple-400 to-pink-400 rounded-full flex items-center justify-center text-white font-bold">
                    {selectedBlog.name?.[0] || 'U'}
                  </div>
                  <div>
                    <div className="font-medium text-gray-800">{selectedBlog.name || '用户'}</div>
                    <div className="text-sm text-gray-500">
                      {selectedBlog.createTime ? new Date(selectedBlog.createTime).toLocaleString() : ''}
                    </div>
                  </div>
                </div>
                <div className="flex items-center space-x-4">
                  <div className="flex items-center space-x-2 text-gray-600">
                    <Heart className="w-5 h-5" />
                    <span>{selectedBlog.liked || 0}</span>
                  </div>
                  <div className="flex items-center space-x-2 text-gray-600">
                    <MessageCircle className="w-5 h-5" />
                    <span>{selectedBlog.comments || 0}</span>
                  </div>
                </div>
              </div>

              <div className="prose max-w-none mb-8">
                <p className="text-gray-700 text-lg leading-relaxed whitespace-pre-wrap">
                  {selectedBlog.content}
                </p>
              </div>

              <div className="flex space-x-4 mb-8">
                <button
                  onClick={(e) => likeBlog(selectedBlog.id, e)}
                  className={`flex-1 py-3 rounded-xl font-medium transition-all ${
                    selectedBlog.isLike
                      ? 'bg-red-500 text-white'
                      : 'bg-gray-100 text-gray-700 hover:bg-red-500 hover:text-white'
                  }`}
                >
                  <Heart className="w-5 h-5 inline mr-2" fill={selectedBlog.isLike ? 'currentColor' : 'none'} />
                  {selectedBlog.isLike ? '已点赞' : '点赞'}
                </button>
              </div>

              {/* 评论区 */}
              <div className="border-t border-gray-200 pt-6">
                <h3 className="text-xl font-bold mb-4">评论 ({comments.length})</h3>
                
                {user && (
                  <div className="flex space-x-3 mb-6">
                    <input
                      type="text"
                      placeholder="写下你的评论..."
                      value={newComment}
                      onChange={(e) => setNewComment(e.target.value)}
                      className="flex-1 px-4 py-3 rounded-xl border-2 border-gray-200 focus:border-purple-400 outline-none"
                      onKeyPress={(e: KeyboardEvent<HTMLInputElement>) => e.key === 'Enter' && postComment()}
                    />
                    <button
                      onClick={postComment}
                      className="px-6 py-3 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-xl hover:shadow-lg transition-all"
                    >
                      <Send className="w-5 h-5" />
                    </button>
                  </div>
                )}

                <div className="space-y-4">
                  {comments.map((comment) => (
                    <div key={comment.id} className="flex space-x-3 p-4 bg-gray-50 rounded-xl">
                      <div className="w-10 h-10 bg-gradient-to-br from-blue-400 to-purple-400 rounded-full flex items-center justify-center text-white font-bold flex-shrink-0">
                        {comment.userName?.[0] || 'U'}
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center space-x-2 mb-1">
                          <span className="font-medium text-gray-800">{comment.userName || '用户'}</span>
                          <span className="text-xs text-gray-500">
                            {comment.createTime ? new Date(comment.createTime).toLocaleString() : ''}
                          </span>
                        </div>
                        <p className="text-gray-700">{comment.content}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 登录弹窗 */}
      {isLogin && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-3xl max-w-md w-full p-8 shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-2xl font-bold text-gray-800">登录</h2>
              <button onClick={() => setIsLogin(false)} className="p-2 hover:bg-gray-100 rounded-full">
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="space-y-4">
              <input
                type="tel"
                placeholder="手机号"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="w-full px-4 py-3 rounded-xl border-2 border-gray-200 focus:border-purple-400 outline-none"
              />
              <div className="flex space-x-2">
                <input
                  type="text"
                  placeholder="验证码"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  className="flex-1 px-4 py-3 rounded-xl border-2 border-gray-200 focus:border-purple-400 outline-none"
                />
                <button
                  onClick={sendCode}
                  disabled={sendingCode}
                  className="px-4 py-3 bg-gray-100 text-gray-700 rounded-xl hover:bg-gray-200 transition-all whitespace-nowrap"
                >
                  {sendingCode ? '发送中...' : '获取验证码'}
                </button>
              </div>
              <button
                onClick={login}
                className="w-full py-3 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-xl font-medium hover:shadow-lg transition-all"
              >
                登录
              </button>
              <p className="text-sm text-gray-500 text-center">验证码登录，未注册将自动创建账号</p>
            </div>
          </div>
        </div>
      )}

      {/* 创建笔记弹窗 */}
      {isCreating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-white rounded-3xl max-w-2xl w-full max-h-[90vh] overflow-y-auto shadow-2xl">
            <div className="p-8">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-2xl font-bold text-gray-800">发布笔记</h2>
                <button onClick={() => setIsCreating(false)} className="p-2 hover:bg-gray-100 rounded-full">
                  <X className="w-6 h-6" />
                </button>
              </div>

              <div className="space-y-4">
                <input
                  type="text"
                  placeholder="给你的笔记起个标题..."
                  value={newBlog.title}
                  onChange={(e) => setNewBlog({...newBlog, title: e.target.value})}
                  className="w-full px-4 py-3 rounded-xl border-2 border-gray-200 focus:border-purple-400 outline-none"
                />
                <input
                  type="text"
                  placeholder="图片URL（多张用逗号分隔）"
                  value={newBlog.images}
                  onChange={(e) => setNewBlog({...newBlog, images: e.target.value})}
                  className="w-full px-4 py-3 rounded-xl border-2 border-gray-200 focus:border-purple-400 outline-none"
                />
                <textarea
                  rows={8}
                  placeholder="分享你的想法..."
                  value={newBlog.content}
                  onChange={(e) => setNewBlog({...newBlog, content: e.target.value})}
                  className="w-full px-4 py-3 rounded-xl border-2 border-gray-200 focus:border-purple-400 outline-none resize-none"
                />
                <button
                  onClick={publishBlog}
                  className="w-full py-3 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-xl font-medium hover:shadow-lg transition-all"
                >
                  发布
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default NoteFlow;