package com.syr.service.Impl;

import cn.hutool.core.bean.BeanUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.syr.entity.Follow;
import com.syr.entity.Note;
import com.syr.mapper.FollowMapper;
import com.syr.service.FeedService;
import com.syr.service.NoteService;
import com.syr.utils.UserHolder;
import com.syr.vo.FeedVO;
import com.syr.vo.NoteVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.stereotype.Service;
import java.util.*;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class FeedServiceImpl implements FeedService {

    private final StringRedisTemplate redisTemplate;
    private final NoteService noteService;
    private final FollowMapper followMapper;

    private static final String FEED_INBOX_KEY = "feed:inbox:";

    @Override
    public FeedVO getFeed(Long lastTimestamp, Integer pageSize) {
        Long currentUserId = UserHolder.getUserId();
        String inboxKey = FEED_INBOX_KEY + currentUserId;

        long maxScore = lastTimestamp == 0 ? System.currentTimeMillis() : lastTimestamp;

        Set<ZSetOperations.TypedTuple<String>> tuples = redisTemplate.opsForZSet()
                .reverseRangeByScoreWithScores(inboxKey, 0, maxScore, 0, pageSize);

        if (tuples == null || tuples.isEmpty()) return FeedVO.empty();

        List<Long> noteIds = new ArrayList<>();
        long nextTimestamp = 0;
        for (ZSetOperations.TypedTuple<String> tuple : tuples) {
            noteIds.add(Long.valueOf(tuple.getValue()));
            nextTimestamp = tuple.getScore().longValue();
        }

        List<Note> notes = noteService.listByIds(noteIds);
        List<NoteVO> noteVOs = notes.stream().map(note -> {
            NoteVO vo = new NoteVO();
            BeanUtil.copyProperties(note, vo);
            return vo;
        }).collect(Collectors.toList());

        return FeedVO.builder()
                .list(noteVOs)
                .nextTimestamp(nextTimestamp)
                .hasMore(tuples.size() == pageSize)
                .build();
    }

    @Override
    public void pushToFans(Long noteId, Long authorId) {
        List<Follow> fans = followMapper.selectList(
                new LambdaQueryWrapper<Follow>().eq(Follow::getFollowUserId, authorId)
        );
        if (fans == null || fans.isEmpty()) return;

        long timestamp = System.currentTimeMillis();
        for (Follow fan : fans) {
            redisTemplate.opsForZSet().add(
                    FEED_INBOX_KEY + fan.getUserId(),
                    noteId.toString(),
                    timestamp
            );
        }
    }
}