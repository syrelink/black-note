package com.syr.service;

import com.syr.vo.FeedVO;

public interface FeedService {
    FeedVO getFeed(Long lastTimestamp, Integer pageSize);
    void pushToFans(Long noteId, Long authorId);
}