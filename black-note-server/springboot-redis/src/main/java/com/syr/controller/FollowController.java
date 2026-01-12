package com.syr.controller;

import com.syr.dto.Result;
import com.syr.entity.Follow;
import com.syr.service.IFollowService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Tag(name = "关注管理", description = "处理用户关注和取消关注的功能")
@RestController
@RequestMapping("/follow")
public class FollowController {

    @Resource
    private IFollowService followService;

    @Operation(summary = "查询指定用户的关注列表")
    @GetMapping("/of/user/{id}")
    public Result queryFollows(@PathVariable("id") Long id) {
        List<Follow> follows = followService.queryFollows(id);
        return Result.ok(follows);
    }

    @Operation(summary = "关注/取消关注用户")
    @PutMapping("/{followUserId}/{isFollow}")
    public Result follow(
            @Parameter(description = "被关注的用户ID", example = "1")
            @PathVariable("followUserId") Long followUserId,
            @Parameter(description = "是否关注", example = "true")
            @PathVariable("isFollow") Boolean isFollow
    ) {
        followService.follow(followUserId, isFollow);
        return Result.ok();
    }

    @Operation(summary = "查询是否关注用户", description = "查询当前用户是否关注了指定用户")
    @Parameter(name = "followUserId", description = "被查询的用户ID", required = true, example = "1")
    @GetMapping("/or/not/{followUserId}")
    public Result isFollow(@PathVariable("followUserId") Long followUserId) {
        boolean isFollowed = followService.isFollow(followUserId);
        return Result.ok(isFollowed);
    }
}
