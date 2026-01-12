package com.syr.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.syr.entity.Follow;

import java.util.List;

public interface IFollowService extends IService<Follow> {

    /**
     * 关注/取消关注
     */
    void follow(Long followUserId, Boolean isFollow);

    /**
     * 查询是否关注
     */
    boolean isFollow(Long followUserId);

    /**
     * 查询关注列表
     */
    List<Follow> queryFollows(Long id);
}
