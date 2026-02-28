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

    // Redis Key 前缀，每个用户的收件箱：feed:inbox:{userId}
    private static final String FEED_INBOX_KEY = "feed:inbox:";

    /**
     * 获取当前用户的关注流（收件箱模式）
     *
     * 原理：Redis ZSet 按时间戳排序存储笔记ID
     * key   = feed:inbox:{userId}
     * value = noteId
     * score = 发布时间戳（越大越新）
     */
    @Override
    public FeedVO getFeed(Long lastTimestamp, Integer pageSize) {
        // 1. 获取当前登录用户ID，拼接收件箱的 Redis Key
        Long currentUserId = UserHolder.getUserId();
        String inboxKey = FEED_INBOX_KEY + currentUserId;

        // 2. 确定查询的时间范围上限
        //    第一次加载：lastTimestamp=0，用当前时间（从最新开始）
        //    加载更多：  lastTimestamp=上次最后一条的时间戳（往前翻页）
        long maxScore = lastTimestamp == 0 ? System.currentTimeMillis() : lastTimestamp;

        // 3. 从 ZSet 中按分数（时间戳）倒序查询
        //    reverseRangeByScoreWithScores(key, 最小分数, 最大分数, 偏移量, 数量)
        //    → 取出 [0, maxScore] 范围内最新的 pageSize 条记录
        //    → 每条记录包含 value(noteId) 和 score(时间戳)
        Set<ZSetOperations.TypedTuple<String>> tuples = redisTemplate.opsForZSet()
                .reverseRangeByScoreWithScores(inboxKey, 0, maxScore, 0, pageSize);

        // 4. 收件箱为空，直接返回空结果
        if (tuples.isEmpty()) return FeedVO.empty();

        // 5. 遍历结果，收集笔记ID 和 最后一条的时间戳
        List<Long> noteIds = new ArrayList<>();
        long nextTimestamp = 0;
        for (ZSetOperations.TypedTuple<String> tuple : tuples) {
            noteIds.add(Long.valueOf(tuple.getValue()));  // 取笔记ID
            nextTimestamp = tuple.getScore().longValue(); // 不断覆盖，最终是最小的时间戳
        }
        // nextTimestamp = 本次结果中最旧那条笔记的时间戳
        // 下次翻页时用这个值作为 maxScore，实现游标翻页，不重复不漏数据

        // 6. 根据笔记ID批量查询笔记详情
        List<Note> notes = noteService.listByIds(noteIds);

        // 7. 将 Note 实体转换为 NoteVO（视图对象，返回给前端）
        List<NoteVO> noteVOs = notes.stream().map(note -> {
            NoteVO vo = new NoteVO();
            BeanUtil.copyProperties(note, vo); // 自动复制同名字段
            return vo;
        }).collect(Collectors.toList());

        // 8. 组装返回结果
        return FeedVO.builder()
                .list(noteVOs)
                .nextTimestamp(nextTimestamp)           // 下次翻页的游标
                .hasMore(tuples.size() == pageSize)     // 返回条数=请求条数 → 可能还有更多
                .build();
    }

    /**
     * 推送笔记到粉丝收件箱（发布笔记时调用）
     *
     * 原理：作者发布笔记后，找到所有粉丝
     *      把笔记ID以当前时间戳为分数写入每个粉丝的收件箱
     */
    @Override
    public void pushToFans(Long noteId, Long authorId) {
        // 1. 查询该作者的所有粉丝
        //    follow 表中 follow_user_id = authorId 的记录，就是作者的粉丝
        List<Follow> fans = followMapper.selectList(
                new LambdaQueryWrapper<Follow>().eq(Follow::getFollowUserId, authorId)
        );

        // 2. 没有粉丝直接返回
        if (fans == null || fans.isEmpty()) return;

        // 3. 用当前时间作为分数（时间戳越大越新，ZSet倒序查询时排在前面）
        long timestamp = System.currentTimeMillis();

        // 4. 遍历所有粉丝，逐个写入收件箱
        for (Follow fan : fans) {
            redisTemplate.opsForZSet().add(
                    FEED_INBOX_KEY + fan.getUserId(), // key：粉丝的收件箱
                    noteId.toString(),                // value：笔记ID
                    timestamp                         // score：发布时间戳
            );
        }
    }
}
