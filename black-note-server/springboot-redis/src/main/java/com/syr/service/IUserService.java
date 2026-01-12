package com.syr.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.syr.dto.LoginFormDto;
import com.syr.entity.User;

public interface IUserService extends IService<User> {

    /**
     * 发送验证码
     * @param phone 手机号
     */
    void sendCode(String phone);

    /**
     * 登录
     * @param loginForm 登录表单
     * @return token令牌
     */
    String login(LoginFormDto loginForm);
}
