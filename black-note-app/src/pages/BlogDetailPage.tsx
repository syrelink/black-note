// src/pages/BlogDetailPage.tsx
import { useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQueryBlogById, useLikeBlog, useQueryBlogLikes } from '../api/generated/博客管理/博客管理';
import type { Blog } from '../api/generated/api.schemas';

function BlogDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [comment, setComment] = useState('');

  const blogId = Number(id);

  // 查询笔记详情
  const { data, isLoading, error, refetch } = useQueryBlogById(blogId);
  const likeMutation = useLikeBlog();
  const { data: likesData } = useQueryBlogLikes(blogId);

  const blog: Blog | undefined = data?.data as Blog;
  const likeUsers = (likesData?.data as any[]) || [];
  const images = blog?.images?.split(',').filter(Boolean) || [];

  const handleLike = async () => {
    try {
      await likeMutation.mutateAsync({ id: blogId });
      refetch();
    } catch (error) {
      console.error('点赞失败:', error);
    }
  };

  const handleSubmitComment = (e: React.FormEvent) => {
    e.preventDefault();
    if (!comment.trim()) return;
    alert('评论功能开发中...');
    setComment('');
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-red-500"></div>
      </div>
    );
  }

  if (error || !blog) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-500 mb-4">笔记不存在或加载失败</p>
          <button
            onClick={() => navigate(-1)}
            className="px-4 py-2 bg-gray-200 rounded-lg hover:bg-gray-300"
          >
            返回
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white">
      {/* 顶部导航 */}
      <div className="sticky top-0 z-20 bg-white border-b">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
          <button
            onClick={() => navigate(-1)}
            className="p-2 hover:bg-gray-100 rounded-full"
          >
            ← 返回
          </button>
          <div className="flex items-center gap-2">
            <img
              src={blog.icon || 'https://via.placeholder.com/32'}
              alt={blog.name}
              className="w-8 h-8 rounded-full object-cover"
            />
            <span className="font-medium text-sm">{blog.name || '匿名用户'}</span>
            <button className="ml-2 px-3 py-1 text-red-500 border border-red-500 rounded-full text-xs hover:bg-red-50">
              关注
            </button>
          </div>
          <button className="p-2 hover:bg-gray-100 rounded-full">
            ⋯
          </button>
        </div>
      </div>

      <div className="max-w-4xl mx-auto">
        <div className="md:flex">
          {/* 左侧 - 图片区域 */}
          <div className="md:w-1/2 bg-black">
            {images.length > 0 ? (
              <div className="relative">
                {/* 主图 */}
                <div className="aspect-[3/4] flex items-center justify-center">
                  <img
                    src={
                      images[currentImageIndex]?.startsWith('http')
                        ? images[currentImageIndex]
                        : `http://localhost:8080/upload/blog/${images[currentImageIndex]}`
                    }
                    alt={blog.title}
                    className="max-w-full max-h-full object-contain"
                    onError={(e) => {
                      (e.target as HTMLImageElement).src = 'https://via.placeholder.com/400x500?text=No+Image';
                    }}
                  />
                </div>

                {/* 图片切换 */}
                {images.length > 1 && (
                  <>
                    <button
                      onClick={() => setCurrentImageIndex((i) => Math.max(0, i - 1))}
                      disabled={currentImageIndex === 0}
                      className="absolute left-2 top-1/2 -translate-y-1/2 w-10 h-10 bg-white/80 rounded-full flex items-center justify-center disabled:opacity-30"
                    >
                      ‹
                    </button>
                    <button
                      onClick={() => setCurrentImageIndex((i) => Math.min(images.length - 1, i + 1))}
                      disabled={currentImageIndex === images.length - 1}
                      className="absolute right-2 top-1/2 -translate-y-1/2 w-10 h-10 bg-white/80 rounded-full flex items-center justify-center disabled:opacity-30"
                    >
                      ›
                    </button>

                    {/* 图片指示器 */}
                    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-1">
                      {images.map((_, i) => (
                        <button
                          key={i}
                          onClick={() => setCurrentImageIndex(i)}
                          className={`w-2 h-2 rounded-full transition-colors ${
                            i === currentImageIndex ? 'bg-white' : 'bg-white/50'
                          }`}
                        />
                      ))}
                    </div>
                  </>
                )}
              </div>
            ) : (
              <div className="aspect-[3/4] flex items-center justify-center bg-gray-100 text-gray-400">
                暂无图片
              </div>
            )}
          </div>

          {/* 右侧 - 内容区域 */}
          <div className="md:w-1/2 flex flex-col">
            {/* 内容 */}
            <div className="flex-1 p-6 overflow-y-auto">
              <h1 className="text-xl font-bold text-gray-900 mb-4">
                {blog.title || '无标题'}
              </h1>
              <p className="text-gray-700 whitespace-pre-wrap leading-relaxed">
                {blog.content || '暂无内容'}
              </p>

              {/* 发布时间 */}
              <div className="mt-6 text-sm text-gray-400">
                {blog.createTime ? new Date(blog.createTime).toLocaleString() : ''}
              </div>

              {/* 点赞用户 */}
              {likeUsers.length > 0 && (
                <div className="mt-6 pt-4 border-t">
                  <p className="text-sm text-gray-500 mb-2">
                    ❤️ {blog.liked || 0} 人喜欢
                  </p>
                  <div className="flex -space-x-2">
                    {likeUsers.slice(0, 5).map((user: any, i: number) => (
                      <img
                        key={i}
                        src={user.icon || 'https://via.placeholder.com/32'}
                        alt={user.nickName}
                        className="w-8 h-8 rounded-full border-2 border-white object-cover"
                      />
                    ))}
                    {likeUsers.length > 5 && (
                      <div className="w-8 h-8 rounded-full border-2 border-white bg-gray-100 flex items-center justify-center text-xs text-gray-500">
                        +{likeUsers.length - 5}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* 评论区 */}
              <div className="mt-6 pt-4 border-t">
                <h3 className="font-medium mb-4">评论 ({blog.comments || 0})</h3>
                <div className="text-center py-8 text-gray-400 text-sm">
                  暂无评论，快来抢沙发吧~
                </div>
              </div>
            </div>

            {/* 底部操作栏 */}
            <div className="border-t p-4">
              <form onSubmit={handleSubmitComment} className="flex gap-2 mb-4">
                <input
                  type="text"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="说点什么..."
                  className="flex-1 px-4 py-2 bg-gray-100 rounded-full text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                />
                <button
                  type="submit"
                  className="px-4 py-2 bg-red-500 text-white rounded-full text-sm hover:bg-red-600"
                >
                  发送
                </button>
              </form>

              <div className="flex justify-around">
                <button
                  onClick={handleLike}
                  className={`flex flex-col items-center gap-1 ${
                    blog.isLike ? 'text-red-500' : 'text-gray-500'
                  }`}
                >
                  <span className="text-2xl">{blog.isLike ? '❤️' : '🤍'}</span>
                  <span className="text-xs">{blog.liked || 0}</span>
                </button>
                <button className="flex flex-col items-center gap-1 text-gray-500">
                  <span className="text-2xl">💬</span>
                  <span className="text-xs">{blog.comments || 0}</span>
                </button>
                <button className="flex flex-col items-center gap-1 text-gray-500">
                  <span className="text-2xl">⭐</span>
                  <span className="text-xs">收藏</span>
                </button>
                <button className="flex flex-col items-center gap-1 text-gray-500">
                  <span className="text-2xl">↗️</span>
                  <span className="text-xs">分享</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default BlogDetailPage;
