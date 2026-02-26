package com.syr.config;


import com.syr.utils.UserHolder;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.util.concurrent.TimeUnit;

@Component
@RequiredArgsConstructor
public class LoginInterceptor implements HandlerInterceptor {

    private final StringRedisTemplate redisTemplate;
    private static final String LOGIN_TOKEN_KEY = "login:token:";

    @Override
    public boolean preHandle(HttpServletRequest request,
                             HttpServletResponse response,
                             Object handler) throws Exception {
        // 从请求头取token
        String token = request.getHeader("Authorization");
        if (token == null || token.isBlank()) {
            response.setStatus(401);
            return false;
        }

        // 从Redis取userId
        String userId = redisTemplate.opsForValue().get(LOGIN_TOKEN_KEY + token);
        if (userId == null) {
            response.setStatus(401);
            return false;
        }

        // 存入ThreadLocal
        UserHolder.setUserId(Long.valueOf(userId));

        // 每次请求续期30分钟
        redisTemplate.expire(LOGIN_TOKEN_KEY + token, 30, TimeUnit.MINUTES);

        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request,
                                HttpServletResponse response,
                                Object handler, Exception ex) {
        // 请求结束清除ThreadLocal，防止内存泄漏
        UserHolder.remove();
    }
}