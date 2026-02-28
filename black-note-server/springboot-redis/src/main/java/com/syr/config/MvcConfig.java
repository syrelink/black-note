package com.syr.config;

import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
@RequiredArgsConstructor
public class MvcConfig implements WebMvcConfigurer {

    private final LoginInterceptor loginInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(loginInterceptor)
                .addPathPatterns("/**")
                .excludePathPatterns(
                        "/user/register",
                        "/user/login",
                        "/user/**",              // 用户信息查询
                        "/note/list",            // 首页公开列表
                        "/note/list/**",         // 用户笔记列表 /note/list/{userId}
                        "/note/like/count/**",   // 点赞数

                        // 注意：/note/like/status/** 不放行，需要登录
                        // 注意：/like/{noteId}
                        // 注意：/note/publish 不放行，需要登录
                        "/swagger-ui.html",
                        "/swagger-ui/**",
                        "/v3/api-docs/**",
                        "/webjars/**"
                );
    }
}