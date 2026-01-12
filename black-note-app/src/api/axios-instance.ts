// src/api/axios-instance.ts
import Axios, { type AxiosRequestConfig } from 'axios';

export const AXIOS_INSTANCE = Axios.create({ 
  baseURL: 'http://localhost:8080',
  headers: {
    'Content-Type': 'application/json',
  }
});

// 请求拦截器 - 自动添加 token
AXIOS_INSTANCE.interceptors.request.use(
  (config) => {
    // 从 localStorage 获取 token
    const token = localStorage.getItem('auth_token');
    
    if (token) {
      config.headers.Authorization = token;
    }
    
    console.log('发送请求:', config.method?.toUpperCase(), config.url);
    return config;
  },
  (error) => {
    console.error('请求错误:', error);
    return Promise.reject(error);
  }
);

// 响应拦截器
AXIOS_INSTANCE.interceptors.response.use(
  (response) => {
    console.log('收到响应:', response.status, response.config.url);
    return response;
  },
  (error) => {
    console.error('响应错误:', error.response?.status, error.message);
    
    // 401 未授权 - 跳转到登录页
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token');
      window.location.href = '/login';
    }
    
    return Promise.reject(error);
  }
);

export const customInstance = <T>(config: AxiosRequestConfig): Promise<T> => {
  const source = Axios.CancelToken.source();
  const promise = AXIOS_INSTANCE({ 
    ...config, 
    cancelToken: source.token 
  }).then(({ data }) => data);

  // @ts-ignore
  promise.cancel = () => {
    source.cancel('Query was cancelled');
  };

  return promise;
};