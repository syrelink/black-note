// src/pages/LoginPage.tsx
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLogin, useSendCode } from '../api/generated/用户管理/用户管理';

function LoginPage() {
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [countdown, setCountdown] = useState(0);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const loginMutation = useLogin();
  const sendCodeMutation = useSendCode();

  // 倒计时效果
  useEffect(() => {
    if (countdown > 0) {
      const timer = setTimeout(() => setCountdown(countdown - 1), 1000);
      return () => clearTimeout(timer);
    }
  }, [countdown]);

  // 验证手机号格式
  const isValidPhone = (phone: string) => {
    return /^1[3-9]\d{9}$/.test(phone);
  };

  // 发送验证码
  const handleSendCode = async () => {
    setError('');

    if (!phone.trim()) {
      setError('请输入手机号');
      return;
    }

    if (!isValidPhone(phone)) {
      setError('请输入正确的手机号格式');
      return;
    }

    try {
      const result = await sendCodeMutation.mutateAsync({
        params: { phone }
      });

      if (result.success) {
        setCountdown(60);
        setError('');
      } else {
        setError(result.errorMsg || '发送失败，请重试');
      }
    } catch (err) {
      console.error('发送验证码失败:', err);
      setError('发送失败，请检查网络连接');
    }
  };

  // 登录
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!phone.trim()) {
      setError('请输入手机号');
      return;
    }

    if (!isValidPhone(phone)) {
      setError('请输入正确的手机号格式');
      return;
    }

    if (!code.trim()) {
      setError('请输入验证码');
      return;
    }

    if (code.length !== 6) {
      setError('请输入6位验证码');
      return;
    }

    try {
      const result = await loginMutation.mutateAsync({
        data: { phone, code }
      });

      if (result.success && result.data) {
        localStorage.setItem('auth_token', result.data.toString());
        navigate('/');
      } else {
        setError(result.errorMsg || '登录失败，请检查验证码');
      }
    } catch (err) {
      console.error('登录失败:', err);
      setError('登录失败，请重试');
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-red-50 to-pink-50 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo 区域 */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-red-500 rounded-2xl mb-4 shadow-lg">
            <span className="text-3xl">📓</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">小黑书</h1>
          <p className="text-sm text-gray-500 mt-1">live to life</p>
        </div>

        {/* 登录表单 */}
        <div className="bg-white rounded-2xl shadow-xl p-8">
          <form onSubmit={handleLogin} className="space-y-5">
            {/* 手机号输入 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                手机号
              </label>
              <input
                type="tel"
                value={phone}
                onChange={(e) => {
                  setPhone(e.target.value.replace(/\D/g, '').slice(0, 11));
                  setError('');
                }}
                placeholder="请输入手机号"
                maxLength={11}
                className="w-full px-4 py-3 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent transition-all text-gray-900 placeholder-gray-400"
              />
            </div>

            {/* 验证码输入 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                验证码
              </label>
              <div className="flex gap-3">
                <input
                  type="text"
                  value={code}
                  onChange={(e) => {
                    setCode(e.target.value.replace(/\D/g, '').slice(0, 6));
                    setError('');
                  }}
                  placeholder="6位验证码"
                  maxLength={6}
                  className="flex-1 px-4 py-3 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent transition-all text-gray-900 placeholder-gray-400"
                />
                <button
                  type="button"
                  onClick={handleSendCode}
                  disabled={countdown > 0 || sendCodeMutation.isPending}
                  className="px-4 py-3 bg-red-50 text-red-500 rounded-xl font-medium text-sm whitespace-nowrap hover:bg-red-100 transition-colors disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
                >
                  {sendCodeMutation.isPending
                    ? '发送中...'
                    : countdown > 0
                    ? `${countdown}s`
                    : '获取验证码'}
                </button>
              </div>
            </div>

            {/* 错误提示 */}
            {error && (
              <div className="text-red-500 text-sm text-center bg-red-50 py-2 rounded-lg">
                {error}
              </div>
            )}

            {/* 登录按钮 */}
            <button
              type="submit"
              disabled={loginMutation.isPending}
              className="w-full py-3 bg-red-500 text-white rounded-xl font-medium hover:bg-red-600 transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed shadow-lg shadow-red-500/30"
            >
              {loginMutation.isPending ? '登录中...' : '登录 / 注册'}
            </button>
          </form>

          {/* 提示文字 */}
          <p className="text-xs text-gray-400 text-center mt-6">
            未注册的手机号将自动创建账号
          </p>
        </div>

        {/* 底部协议 */}
        <p className="text-xs text-gray-400 text-center mt-6">
          登录即表示同意
          <span className="text-red-500 cursor-pointer"> 用户协议 </span>
          和
          <span className="text-red-500 cursor-pointer"> 隐私政策</span>
        </p>
      </div>
    </div>
  );
}

export default LoginPage;
