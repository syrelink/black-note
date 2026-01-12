 package com.syr.config;

 import com.syr.utils.LoginInterceptor;
 import com.syr.utils.RefreshTokenInterceptor;
 import jakarta.annotation.Resource;
 import org.springframework.context.annotation.Configuration;
 import org.springframework.web.servlet.config.annotation.CorsRegistry;
 import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
 import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
 import org.springframework.data.redis.core.StringRedisTemplate;

 @Configuration
 public class MvcConfig implements WebMvcConfigurer {

     @Resource
     private StringRedisTemplate stringRedisTemplate;
     // --- 新增跨域配置 ---
     @Override
     public void addCorsMappings(CorsRegistry registry) {
         registry.addMapping("/**") // 允许跨域访问的路径
                 .allowedOriginPatterns("*") // 允许跨域访问的源（生产环境建议写具体域名）
                 .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS") // 允许的请求方式
                 .allowedHeaders("*") // 允许的请求头
                 .allowCredentials(true) // 是否允许发送 Cookie/Token
                 .maxAge(3600); // 预检请求的有效期
     }
     @Override
     public void addInterceptors(InterceptorRegistry registry) {
         // 登录拦截器
         registry.addInterceptor(new LoginInterceptor())
                 .excludePathPatterns(
                         "/user/code",
                         "/user/login",
                         // --- 必须放行的 Swagger 路径 ---
                         "/swagger-ui.html",     // 静态首页
                         "/swagger-ui/**",       // 静态资源
                         "/v3/api-docs/**",      // 核心 JSON 数据接口
                         "/webjars/**",          // 网页依赖
                         "/swagger-resources/**"
                 ).order(1);

         // token刷新拦截器
         registry.addInterceptor(new RefreshTokenInterceptor(stringRedisTemplate)).addPathPatterns("/**").order(0);
     }
 }
