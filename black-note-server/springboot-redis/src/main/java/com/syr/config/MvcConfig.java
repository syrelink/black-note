package com.syr.config;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
@Configuration
@RequiredArgsConstructor
public class MvcConfig implements WebMvcConfigurer {

    private final TokenInterceptor tokenInterceptor;
    private final LoginInterceptor loginInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // order(0) 先执行，所有请求都过，只负责解析 token
        registry.addInterceptor(tokenInterceptor)
                .addPathPatterns("/**")
                .order(0);

        // order(1) 后执行，只拦截需要登录的接口
        registry.addInterceptor(loginInterceptor)
                .addPathPatterns("/**")
                .excludePathPatterns(
                        "/user/register",
                        "/user/login",
                        "/note/list",
                        "/note/list/**",
                        "/note/{id}",
                        "/note/like/count/**",
                        "/swagger-ui/**",
                        "/v3/api-docs/**",
                        "/webjars/**"
                )
                .order(1);
    }
}