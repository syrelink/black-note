// src/pages/CreateBlogPage.tsx
import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSaveBlog } from '../api/generated/博客管理/博客管理';
import { AXIOS_INSTANCE } from '../api/axios-instance';

function CreateBlogPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [images, setImages] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);

  const saveBlogMutation = useSaveBlog();

  // 上传图片
  const handleUploadImage = async (files: FileList | null) => {
    if (!files || files.length === 0) return;

    setUploading(true);
    const uploadedImages: string[] = [];

    try {
      for (const file of Array.from(files)) {
        const formData = new FormData();
        formData.append('file', file);

        const response = await AXIOS_INSTANCE.post('/upload/blog', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });

        if (response.data?.data) {
          uploadedImages.push(response.data.data);
        }
      }

      setImages((prev) => [...prev, ...uploadedImages]);
    } catch (error) {
      console.error('上传失败:', error);
      alert('图片上传失败，请重试');
    } finally {
      setUploading(false);
    }
  };

  // 删除图片
  const handleRemoveImage = (index: number) => {
    setImages((prev) => prev.filter((_, i) => i !== index));
  };

  // 发布笔记
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!title.trim()) {
      alert('请输入标题');
      return;
    }

    if (images.length === 0) {
      alert('请至少上传一张图片');
      return;
    }

    try {
      const result = await saveBlogMutation.mutateAsync({
        data: {
          title,
          content,
          images: images.join(','),
        },
      });

      if (result.success) {
        alert('发布成功！');
        navigate('/blogs');
      } else {
        alert(result.errorMsg || '发布失败');
      }
    } catch (error) {
      console.error('发布失败:', error);
      alert('发布失败，请重试');
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部导航 */}
      <div className="sticky top-0 z-10 bg-white border-b">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center justify-between">
          <button
            onClick={() => navigate(-1)}
            className="text-gray-600 hover:text-gray-900"
          >
            取消
          </button>
          <h1 className="font-medium">发布笔记</h1>
          <button
            onClick={handleSubmit}
            disabled={saveBlogMutation.isPending || !title.trim() || images.length === 0}
            className="px-4 py-1.5 bg-red-500 text-white rounded-full text-sm font-medium hover:bg-red-600 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {saveBlogMutation.isPending ? '发布中...' : '发布'}
          </button>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6">
        {/* 图片上传区域 */}
        <div className="mb-6">
          <div className="grid grid-cols-3 gap-3">
            {/* 已上传的图片 */}
            {images.map((img, index) => (
              <div key={index} className="relative aspect-square rounded-lg overflow-hidden bg-gray-100">
                <img
                  src={img.startsWith('http') ? img : `http://localhost:8080/upload/blog/${img}`}
                  alt={`上传图片 ${index + 1}`}
                  className="w-full h-full object-cover"
                />
                <button
                  onClick={() => handleRemoveImage(index)}
                  className="absolute top-1 right-1 w-6 h-6 bg-black/50 text-white rounded-full flex items-center justify-center text-sm hover:bg-black/70"
                >
                  ×
                </button>
                {index === 0 && (
                  <span className="absolute bottom-1 left-1 px-2 py-0.5 bg-black/50 text-white text-xs rounded">
                    封面
                  </span>
                )}
              </div>
            ))}

            {/* 上传按钮 */}
            {images.length < 9 && (
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="aspect-square rounded-lg border-2 border-dashed border-gray-300 flex flex-col items-center justify-center text-gray-400 hover:border-red-500 hover:text-red-500 transition-colors disabled:opacity-50"
              >
                {uploading ? (
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-400"></div>
                ) : (
                  <>
                    <span className="text-3xl mb-1">+</span>
                    <span className="text-xs">添加图片</span>
                  </>
                )}
              </button>
            )}
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            onChange={(e) => handleUploadImage(e.target.files)}
            className="hidden"
          />

          <p className="mt-2 text-xs text-gray-400">
            最多上传 9 张图片，第一张为封面
          </p>
        </div>

        {/* 标题输入 */}
        <div className="mb-4">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="填写标题会有更多赞哦~"
            maxLength={100}
            className="w-full px-0 py-3 text-xl font-medium border-0 border-b border-gray-200 focus:outline-none focus:border-red-500 bg-transparent"
          />
          <div className="text-right text-xs text-gray-400 mt-1">
            {title.length}/100
          </div>
        </div>

        {/* 内容输入 */}
        <div className="mb-6">
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="添加正文..."
            rows={10}
            maxLength={2000}
            className="w-full px-0 py-3 border-0 focus:outline-none resize-none bg-transparent text-gray-700"
          />
          <div className="text-right text-xs text-gray-400">
            {content.length}/2000
          </div>
        </div>

        {/* 其他选项 */}
        <div className="space-y-4 border-t pt-4">
          <button className="w-full flex items-center justify-between py-3 text-gray-700 hover:bg-gray-50 rounded-lg px-2">
            <span className="flex items-center gap-3">
              <span>📍</span>
              <span>添加地点</span>
            </span>
            <span className="text-gray-400">›</span>
          </button>
          <button className="w-full flex items-center justify-between py-3 text-gray-700 hover:bg-gray-50 rounded-lg px-2">
            <span className="flex items-center gap-3">
              <span>#️⃣</span>
              <span>添加话题</span>
            </span>
            <span className="text-gray-400">›</span>
          </button>
          <button className="w-full flex items-center justify-between py-3 text-gray-700 hover:bg-gray-50 rounded-lg px-2">
            <span className="flex items-center gap-3">
              <span>@</span>
              <span>提及用户</span>
            </span>
            <span className="text-gray-400">›</span>
          </button>
        </div>
      </div>
    </div>
  );
}

export default CreateBlogPage;
