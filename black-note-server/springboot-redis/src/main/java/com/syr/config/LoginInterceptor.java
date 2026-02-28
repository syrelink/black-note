package com.syr.config;


import com.syr.exception.BusinessException;
import com.syr.utils.UserHolder;

import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

@Component
public class LoginInterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request,
                             HttpServletResponse response,
                             Object handler) throws Exception {
        if (UserHolder.getUserId() == null) {
            throw new BusinessException(401, "未登录，请先登录");
        }
        return true;
    }
}