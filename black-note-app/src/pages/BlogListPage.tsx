// src/pages/BlogListPage.tsx
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQueryHotBlog, useLikeBlog } from '../api/generated/博客管理/博客管理';
import type { Blog } from '../api/generated/api.schemas';

// 笔记卡片组件
function BlogCard({ blog, onLike }: { blog: Blog; onLike: (id: number) => void }) {
  const images = blog.images?.split(',') || [];
  const firstImage = images[0] || '/placeholder.jpg';

  return (
    <div className="bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow">
      {/* 图片区域 */}
      <Link to={`/blog/${blog.id}`}>
        <div className="relative aspect-[3/4] overflow-hidden">
          <img
            src={firstImage.startsWith('http') ? firstImage : `http://localhost:8080/upload/blog/${firstImage}`}
            alt={blog.title}
            className="w-full h-full object-cover hover:scale-105 transition-transform duration-300"
            onError={(e) => {
              (e.target as HTMLImageElement).src = 'https://via.placeholder.com/300x400?text=No+Image';
            }}
          />
          {images.length > 1 && (
            <div className="absolute top-2 right-2 bg-black/50 text-white text-xs px-2 py-1 rounded-full">
              {images.length} 图
            </div>
          )}
        </div>
      </Link>

      {/* 内容区域 */}
      <div className="p-3">
        <Link to={`/blog/${blog.id}`}>
          <h3 className="font-medium text-gray-900 text-sm line-clamp-2 mb-2 hover:text-red-500">
            {blog.title || '无标题'}
          </h3>
        </Link>

        {/* 作者信息 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <img
              src={blog.icon || 'https://via.placeholder.com/32'}
              alt={blog.name}
              className="w-6 h-6 rounded-full object-cover"
              onError={(e) => {
                (e.target as HTMLImageElement).src = 'https://via.placeholder.com/32';
              }}
            />
            <span className="text-xs text-gray-500 truncate max-w-[80px]">
              {blog.name || '匿名用户'}
            </span>
          </div>

          {/* 点赞 */}
          <button
            onClick={(e) => {
              e.preventDefault();
              if (blog.id) onLike(blog.id);
            }}
            className={`flex items-center gap-1 text-xs ${
              blog.isLike ? 'text-red-500' : 'text-gray-400'
            } hover:text-red-500 transition-colors`}
          >
            <span>{blog.isLike ? '❤️' : '🤍'}</span>
            <span>{blog.liked || 0}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function BlogListPage() {
  const [currentPage, setCurrentPage] = useState(1);
  const navigate = useNavigate();

  // 查询热门笔记
  const { data, isLoading, error, refetch } = useQueryHotBlog({ current: currentPage });
  const likeMutation = useLikeBlog();

  const blogs: Blog[] = (data?.data as Blog[]) || [];

  const handleLike = async (id: number) => {
    try {
      await likeMutation.mutateAsync({ id });
      refetch(); // 刷新列表
    } catch (error) {
      console.error('点赞失败:', error);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-red-500 mx-auto mb-4"></div>
          <p className="text-gray-500">加载中...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-500 mb-4">加载失败</p>
          <button
            onClick={() => refetch()}
            className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600"
          >
            重试
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部搜索栏 */}
      <div className="sticky top-0 z-10 bg-white border-b px-4 py-3">
        <div className="max-w-6xl mx-auto flex items-center gap-4">
          <div className="flex-1 relative">
            <input
              type="text"
              placeholder="搜索笔记、用户..."
              className="w-full pl-10 pr-4 py-2 bg-gray-100 rounded-full text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
            />
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">🔍</span>
          </div>
          <button
            onClick={() => navigate('/blog/create')}
            className="flex items-center gap-2 px-4 py-2 bg-red-500 text-white rounded-full text-sm font-medium hover:bg-red-600 transition-colors"
          >
            <span>✏️</span>
            <span>发布</span>
          </button>
        </div>
      </div>

      {/* Tab 切换 */}
      <div className="sticky top-[61px] z-10 bg-white border-b">
        <div className="max-w-6xl mx-auto flex justify-center">
          <button className="px-6 py-3 text-red-500 border-b-2 border-red-500 font-medium">
            发现
          </button>
          <button className="px-6 py-3 text-gray-500 hover:text-gray-700">
            关注
          </button>
          <button className="px-6 py-3 text-gray-500 hover:text-gray-700">
            附近
          </button>
        </div>
      </div>

      {/* 瀑布流列表 */}
      <div className="max-w-6xl mx-auto px-4 py-6">
        {blogs.length === 0 ? (
          <div className="text-center py-20">
            <div className="text-6xl mb-4">📝</div>
            <p className="text-gray-500 mb-4">还没有笔记，快来发布第一篇吧！</p>
            <button
              onClick={() => navigate('/blog/create')}
              className="px-6 py-2 bg-red-500 text-white rounded-full hover:bg-red-600"
            >
              发布笔记
            </button>
          </div>
        ) : (
          <>
            {/* 瀑布流布局 - 使用 CSS columns */}
            <div className="columns-2 md:columns-3 lg:columns-4 xl:columns-5 gap-4">
              {blogs.map((blog) => (
                <div key={blog.id} className="break-inside-avoid mb-4">
                  <BlogCard blog={blog} onLike={handleLike} />
                </div>
              ))}
            </div>

            {/* 分页 */}
            <div className="flex justify-center gap-2 mt-8">
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="px-4 py-2 bg-white border rounded-lg disabled:opacity-50 hover:bg-gray-50"
              >
                上一页
              </button>
              <span className="px-4 py-2 bg-red-500 text-white rounded-lg">
                {currentPage}
              </span>
              <button
                onClick={() => setCurrentPage((p) => p + 1)}
                disabled={blogs.length < 10}
                className="px-4 py-2 bg-white border rounded-lg disabled:opacity-50 hover:bg-gray-50"
              >
                下一页
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default BlogListPage;
