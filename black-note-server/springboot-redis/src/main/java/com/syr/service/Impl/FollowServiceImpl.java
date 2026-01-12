package com.syr.service.Impl;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.entity.Follow;
import com.syr.mapper.FollowMapper;
import com.syr.service.IFollowService;
import com.syr.utils.UserHolder;
import org.springframework.stereotype.Service;

import java.util.Collections;
import java.util.List;

@Service
public class FollowServiceImpl extends ServiceImpl<FollowMapper, Follow> implements IFollowService {

    @Override
    public void follow(Long followUserId, Boolean isFollow) {
        Long userId = UserHolder.getUser().getId();

        if (isFollow) {
            Follow follow = new Follow();
            follow.setFollowUserId(followUserId);
            follow.setUserId(userId);
            save(follow);
        } else {
            remove(new QueryWrapper<Follow>()
                    .eq("user_id", userId)
                    .eq("follow_user_id", followUserId));
        }
    }

    @Override
    public boolean isFollow(Long followUserId) {
        Long userId = UserHolder.getUser().getId();
        Long count = query().eq("user_id", userId).eq("follow_user_id", followUserId).count();
        return count > 0;
    }

    @Override
    public List<Follow> queryFollows(Long id) {
        List<Follow> follows = query().eq("user_id", id).list();
        if (follows == null || follows.isEmpty()) {
            return Collections.emptyList();
        }
        return follows;
    }
}
