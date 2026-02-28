package com.syr.controller;

import com.syr.dto.Result;
import com.syr.service.FollowService;
import com.syr.vo.UserVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/follow")
@RequiredArgsConstructor
public class FollowController {

    private final FollowService followService;

    @PostMapping("/{userId}")
    public Result<Void> follow(@PathVariable Long userId) {
        followService.follow(userId);
        return Result.success();
    }
    @GetMapping("/list/{userId}")
    public Result<List<UserVO>> followList(@PathVariable Long userId) {
        return Result.success(followService.followList(userId));
    }
    @GetMapping("/isFollow/{userId}")
    public Result<Boolean> isFollow(@PathVariable Long userId) {
        return Result.success(followService.isFollow(userId));
    }

    @GetMapping("/common/{userId}")
    public Result<List<UserVO>> commonFollow(@PathVariable Long userId) {
        return Result.success(followService.commonFollow(userId));
    }
}