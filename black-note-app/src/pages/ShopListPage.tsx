// src/pages/ShopListPage.tsx
import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { AXIOS_INSTANCE } from '../api/axios-instance';
import type { Shop } from '../api/generated/api.schemas';

// 店铺卡片组件
function ShopCard({ shop }: { shop: Shop }) {
  const images = shop.images?.split(',') || [];
  const firstImage = images[0] || '';

  return (
    <Link
      to={`/shop/${shop.id}`}
      className="bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-all hover:-translate-y-1"
    >
      {/* 店铺图片 */}
      <div className="relative h-40 overflow-hidden">
        <img
          src={firstImage.startsWith('http') ? firstImage : `http://localhost:8080/upload/shop/${firstImage}`}
          alt={shop.name}
          className="w-full h-full object-cover"
          onError={(e) => {
            (e.target as HTMLImageElement).src = 'https://via.placeholder.com/400x200?text=Shop';
          }}
        />
        {/* 评分标签 */}
        <div className="absolute top-2 right-2 bg-orange-500 text-white text-xs px-2 py-1 rounded-full font-medium">
          ⭐ {shop.score || 0}
        </div>
      </div>

      {/* 店铺信息 */}
      <div className="p-4">
        <h3 className="font-bold text-gray-900 mb-1 truncate">{shop.name || '未知店铺'}</h3>

        <div className="flex items-center text-xs text-gray-500 mb-2">
          <span className="text-orange-500 font-medium">¥{shop.avgPrice || 0}/人</span>
          <span className="mx-2">·</span>
          <span>{shop.area || '未知区域'}</span>
        </div>

        <p className="text-xs text-gray-400 truncate">
          📍 {shop.address || '暂无地址'}
        </p>

        <div className="mt-3 flex items-center justify-between text-xs text-gray-400">
          <span>💬 {shop.comments || 0} 条评价</span>
          <span>🛒 {shop.sold || 0} 已售</span>
        </div>
      </div>
    </Link>
  );
}

function ShopListPage() {
  const [shops, setShops] = useState<Shop[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  // 获取店铺列表
  useEffect(() => {
    const fetchShops = async () => {
      setLoading(true);
      try {
        const response = await AXIOS_INSTANCE.get('/shop/list', {
          params: { current: currentPage }
        });

        if (response.data?.success) {
          setShops(response.data.data || []);
        } else {
          // 如果API不存在，使用模拟数据
          setShops([
            {
              id: 1,
              name: '星巴克咖啡',
              images: 'https://images.unsplash.com/photo-1453614512568-c4024d13c247?w=400',
              address: '北京市朝阳区建国路88号',
              area: '国贸商圈',
              avgPrice: 45,
              score: 4.8,
              comments: 1234,
              sold: 5678,
            },
            {
              id: 2,
              name: '海底捞火锅',
              images: 'https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=400',
              address: '北京市海淀区中关村大街1号',
              area: '中关村',
              avgPrice: 128,
              score: 4.9,
              comments: 8765,
              sold: 12345,
            },
            {
              id: 3,
              name: '喜茶',
              images: 'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400',
              address: '北京市西城区西单北大街120号',
              area: '西单商圈',
              avgPrice: 32,
              score: 4.7,
              comments: 2345,
              sold: 9876,
            },
            {
              id: 4,
              name: '西贝莜面村',
              images: 'https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?w=400',
              address: '北京市东城区王府井大街138号',
              area: '王府井',
              avgPrice: 88,
              score: 4.6,
              comments: 3456,
              sold: 7654,
            },
          ]);
        }
      } catch (err) {
        console.error('获取店铺列表失败:', err);
        // 使用模拟数据
        setShops([
          {
            id: 1,
            name: '星巴克咖啡',
            images: 'https://images.unsplash.com/photo-1453614512568-c4024d13c247?w=400',
            address: '北京市朝阳区建国路88号',
            area: '国贸商圈',
            avgPrice: 45,
            score: 4.8,
            comments: 1234,
            sold: 5678,
          },
          {
            id: 2,
            name: '海底捞火锅',
            images: 'https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=400',
            address: '北京市海淀区中关村大街1号',
            area: '中关村',
            avgPrice: 128,
            score: 4.9,
            comments: 8765,
            sold: 12345,
          },
        ]);
      } finally {
        setLoading(false);
      }
    };

    fetchShops();
  }, [currentPage]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-red-500 mx-auto mb-4"></div>
          <p className="text-gray-500">加载中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部搜索栏 */}
      <div className="sticky top-0 z-10 bg-white border-b px-4 py-3">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-4">
            <div className="flex-1 relative">
              <input
                type="text"
                placeholder="搜索店铺、美食..."
                className="w-full pl-10 pr-4 py-2 bg-gray-100 rounded-full text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
              />
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">🔍</span>
            </div>
          </div>
        </div>
      </div>

      {/* 分类筛选 */}
      <div className="bg-white border-b overflow-x-auto">
        <div className="max-w-6xl mx-auto px-4 py-3 flex gap-4">
          {['全部', '美食', '咖啡', '奶茶', '火锅', '烧烤', '日料', '西餐'].map((cat) => (
            <button
              key={cat}
              className={`px-4 py-1.5 rounded-full text-sm whitespace-nowrap ${
                cat === '全部'
                  ? 'bg-red-500 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* 店铺列表 */}
      <div className="max-w-6xl mx-auto px-4 py-6">
        {shops.length === 0 ? (
          <div className="text-center py-20">
            <div className="text-6xl mb-4">🏪</div>
            <p className="text-gray-500">暂无店铺信息</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {shops.map((shop) => (
                <ShopCard key={shop.id} shop={shop} />
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
                disabled={shops.length < 10}
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

export default ShopListPage;
