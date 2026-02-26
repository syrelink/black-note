package com.syr.mq;

import com.syr.entity.Note;
import com.syr.entity.NoteLike;
import com.syr.mapper.NoteLikeMapper;
import com.syr.service.FeedService;
import com.syr.service.NoteService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import com.syr.config.RabbitMQConfig;
@Slf4j
@Component
@RequiredArgsConstructor
public class MQConsumer {

    private final NoteLikeMapper noteLikeMapper;
    private final NoteService noteService;
    private final FeedService feedService;
    private final StringRedisTemplate redisTemplate;

    // 点赞落库（唯一索引防重复，DuplicateKeyException保幂等）
    @RabbitListener(queues = RabbitMQConfig.LIKE_ADD_QUEUE)
    public void handleLikeAdd(LikeMQMessage msg) {
        try {
            NoteLike noteLike = new NoteLike();
            noteLike.setUserId(msg.getUserId());
            noteLike.setNoteId(msg.getNoteId());
            noteLikeMapper.insert(noteLike);

            noteService.lambdaUpdate()
                    .eq(Note::getId, msg.getNoteId())
                    .setSql("like_count = like_count + 1")
                    .update();
        } catch (DuplicateKeyException e) {
            log.warn("重复点赞消息，忽略。userId={}, noteId={}", msg.getUserId(), msg.getNoteId());
        }
    }

    // 取消点赞落库
    @RabbitListener(queues = RabbitMQConfig.LIKE_CANCEL_QUEUE)
    public void handleLikeCancel(LikeMQMessage msg) {
        noteLikeMapper.deleteByUserIdAndNoteId(msg.getUserId(), msg.getNoteId());
        noteService.lambdaUpdate()
                .eq(Note::getId, msg.getNoteId())
                .setSql("like_count = like_count - 1")
                .update();
    }

    // Feed推送：写粉丝收件箱
    @RabbitListener(queues = RabbitMQConfig.FEED_PUSH_QUEUE)
    public void handleFeedPush(Long noteId) {
        Note note = noteService.getById(noteId);
        if (note == null) return;
        feedService.pushToFans(noteId, note.getUserId());
    }

    // 缓存删除补偿
    @RabbitListener(queues = RabbitMQConfig.CACHE_DELETE_QUEUE)
    public void handleCacheDelete(String key) {
        try {
            redisTemplate.delete(key);
            log.info("缓存补偿删除成功，key={}", key);
        } catch (Exception e) {
            log.error("缓存补偿删除失败，key={}，需人工介入", key, e);
        }
    }
}