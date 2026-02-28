package com.syr.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.syr.entity.Follow;
import com.syr.vo.UserVO;
import java.util.List;

public interface FollowService extends IService<Follow> {
    void follow(Long targetUserId);
    Boolean isFollow(Long targetUserId);
    List<UserVO> commonFollow(Long targetUserId);

    List<UserVO> followList(Long userId);
}