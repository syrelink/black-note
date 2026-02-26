package com.syr.service.Impl;

import cn.hutool.core.bean.BeanUtil;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.entity.Follow;
import com.syr.entity.User;
import com.syr.mapper.FollowMapper;
import com.syr.service.FollowService;
import com.syr.service.UserService;
import com.syr.utils.UserHolder;
import com.syr.vo.UserVO;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import java.util.*;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class FollowServiceImpl extends ServiceImpl<FollowMapper, Follow> implements FollowService {

    private final StringRedisTemplate redisTemplate;
    private final UserService userService;

    private static final String FOLLOW_KEY = "follow:";

    @Override
    public void follow(Long targetUserId) {
        Long currentUserId = UserHolder.getUserId();
        String followKey = FOLLOW_KEY + currentUserId;

        Boolean isFollow = redisTemplate.opsForSet().isMember(followKey, targetUserId.toString());

        if (Boolean.TRUE.equals(isFollow)) {
            lambdaUpdate()
                    .eq(Follow::getUserId, currentUserId)
                    .eq(Follow::getFollowUserId, targetUserId)
                    .remove();
            redisTemplate.opsForSet().remove(followKey, targetUserId.toString());
        } else {
            Follow follow = new Follow();
            follow.setUserId(currentUserId);
            follow.setFollowUserId(targetUserId);
            save(follow);
            redisTemplate.opsForSet().add(followKey, targetUserId.toString());
        }
    }

    @Override
    public Boolean isFollow(Long targetUserId) {
        Long currentUserId = UserHolder.getUserId();
        return Boolean.TRUE.equals(
                redisTemplate.opsForSet().isMember(FOLLOW_KEY + currentUserId, targetUserId.toString())
        );
    }

    @Override
    public List<UserVO> commonFollow(Long targetUserId) {
        Long currentUserId = UserHolder.getUserId();
        Set<String> commonIds = redisTemplate.opsForSet()
                .intersect(FOLLOW_KEY + currentUserId, FOLLOW_KEY + targetUserId);

        if (commonIds == null || commonIds.isEmpty()) return Collections.emptyList();

        List<Long> idList = commonIds.stream().map(Long::valueOf).collect(Collectors.toList());
        List<User> users = userService.listByIds(idList);

        return users.stream().map(user -> {
            UserVO vo = new UserVO();
            BeanUtil.copyProperties(user, vo);
            return vo;
        }).collect(Collectors.toList());
    }
}