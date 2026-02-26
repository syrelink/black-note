package com.syr.controller;

import com.syr.dto.Result;
import com.syr.service.FeedService;
import com.syr.vo.FeedVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/feed")
@RequiredArgsConstructor
public class FeedController {

    private final FeedService feedService;

    @GetMapping
    public Result<FeedVO> getFeed(
            @RequestParam(defaultValue = "0") Long lastTimestamp,
            @RequestParam(defaultValue = "10") Integer pageSize) {
        return Result.success(feedService.getFeed(lastTimestamp, pageSize));
    }
}