package com.syr.service.Impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.lang.UUID;
import cn.hutool.crypto.digest.BCrypt;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.exception.BusinessException;
import com.syr.dto.LoginDTO;
import com.syr.dto.RegisterDTO;
import com.syr.entity.User;
import com.syr.mapper.UserMapper;
import com.syr.service.UserService;
import com.syr.vo.UserVO;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import java.util.concurrent.TimeUnit;

@Service
@RequiredArgsConstructor
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements UserService {

    private final StringRedisTemplate redisTemplate;
    private static final String TOKEN_KEY = "login:token:";
    private static final long   TOKEN_TTL = 30L;

    @Override
    public void register(RegisterDTO dto) {
        Long count = lambdaQuery().eq(User::getUsername, dto.getUsername()).count();
        if (count > 0) throw new BusinessException(400, "用户名已存在");

        User user = new User();
        user.setUsername(dto.getUsername());
        user.setPassword(BCrypt.hashpw(dto.getPassword()));
        save(user);
    }

    @Override
    public String login(LoginDTO dto) {
        User user = lambdaQuery().eq(User::getUsername, dto.getUsername()).one();
        if (user == null || !BCrypt.checkpw(dto.getPassword(), user.getPassword())) {
            throw new BusinessException(400, "用户名或密码错误");
        }
        String token = UUID.randomUUID().toString(true);
        redisTemplate.opsForValue().set(TOKEN_KEY + token, user.getId().toString(), TOKEN_TTL, TimeUnit.MINUTES);
        return token;
    }

    @Override
    public UserVO getUserById(Long id) {
        User user = getById(id);
        if (user == null) throw new BusinessException(404, "用户不存在");
        UserVO vo = new UserVO();
        BeanUtil.copyProperties(user, vo);
        return vo;
    }
}