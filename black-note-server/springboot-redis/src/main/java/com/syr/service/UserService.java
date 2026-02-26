package com.syr.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.syr.dto.LoginDTO;
import com.syr.dto.RegisterDTO;
import com.syr.entity.User;
import com.syr.vo.UserVO;

public interface UserService extends IService<User> {
    void register(RegisterDTO dto);
    String login(LoginDTO dto);
    UserVO getUserById(Long id);
}