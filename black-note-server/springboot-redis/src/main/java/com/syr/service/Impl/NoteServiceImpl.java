package com.syr.service.Impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.json.JSONUtil;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.exception.BusinessException;
import com.syr.dto.NotePublishDTO;
import com.syr.entity.Note;
import com.syr.mapper.NoteMapper;
import com.syr.mq.LikeMQMessage;
import com.syr.service.NoteService;
import com.syr.utils.UserHolder;
import com.syr.vo.NoteVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;
import com.syr.utils.SystemConstants;
import com.syr.config.RabbitMQConfig;

@Slf4j
@Service
@RequiredArgsConstructor
public class NoteServiceImpl extends ServiceImpl<NoteMapper, Note> implements NoteService {

    private final StringRedisTemplate redisTemplate;
    private final RabbitTemplate rabbitTemplate;

    @Override
    public void publish(NotePublishDTO dto) {
        Long userId = UserHolder.getUserId();
        Note note = new Note();
        note.setUserId(userId);
        note.setTitle(dto.getTitle());
        note.setContent(dto.getContent());
        if (dto.getImages() != null && !dto.getImages().isEmpty()) {
            note.setImages(String.join(",", dto.getImages()));
        }
        save(note);
        rabbitTemplate.convertAndSend(RabbitMQConfig.FEED_EXCHANGE, RabbitMQConfig.FEED_PUSH_KEY, note.getId());
    }

    @Override
    public NoteVO getNoteById(Long id) {
        String key = SystemConstants.NOTE_DETAIL_KEY + id;
        String json = redisTemplate.opsForValue().get(key);

        if (json != null) {
            if (SystemConstants.CACHE_NULL_VALUE.equals(json)) return null;
            return JSONUtil.toBean(json, NoteVO.class);
        }

        Note note = getById(id);
        if (note == null) {
            redisTemplate.opsForValue().set(key, SystemConstants.CACHE_NULL_VALUE, SystemConstants.CACHE_NULL_TTL, TimeUnit.MINUTES);
            return null;
        }

        NoteVO vo = convertToVO(note);
        redisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(vo), SystemConstants.CACHE_TTL, TimeUnit.MINUTES);
        return vo;
    }

    @Override
    @Transactional
    public void deleteNote(Long id) {
        Long userId = UserHolder.getUserId();
        Note note = getById(id);
        if (note == null) throw new BusinessException(404, "笔记不存在");
        if (!note.getUserId().equals(userId)) throw new BusinessException(403, "无权限删除");

        removeById(id);

        String key = SystemConstants.NOTE_DETAIL_KEY + id;
        try {
            redisTemplate.delete(key);
        } catch (Exception e) {
            log.error("删除缓存失败，发MQ补偿，key={}", key, e);
            rabbitTemplate.convertAndSend(RabbitMQConfig.CACHE_EXCHANGE, RabbitMQConfig.CACHE_DELETE_KEY, key);
        }
    }

    @Override
    public List<NoteVO> listByUser(Long userId) {
        List<Note> notes = lambdaQuery()
                .eq(Note::getUserId, userId)
                .orderByDesc(Note::getCreatedAt)
                .list();
        if (notes == null || notes.isEmpty()) return Collections.emptyList();
        return notes.stream().map(this::convertToVO).collect(Collectors.toList());
    }

    @Override
    public void like(Long noteId) {
        Long userId = UserHolder.getUserId();
        String likeSetKey   = SystemConstants.NOTE_LIKE_SET_KEY + noteId;
        String likeCountKey = SystemConstants.NOTE_LIKE_COUNT_KEY + noteId;

        Boolean isMember = redisTemplate.opsForSet().isMember(likeSetKey, userId.toString());

        if (Boolean.TRUE.equals(isMember)) {
            redisTemplate.opsForSet().remove(likeSetKey, userId.toString());
            redisTemplate.opsForValue().decrement(likeCountKey);
            rabbitTemplate.convertAndSend(RabbitMQConfig.LIKE_EXCHANGE, RabbitMQConfig.LIKE_CANCEL_KEY,
                    new LikeMQMessage(userId, noteId));
        } else {
            redisTemplate.opsForSet().add(likeSetKey, userId.toString());
            redisTemplate.opsForValue().increment(likeCountKey);
            rabbitTemplate.convertAndSend(RabbitMQConfig.LIKE_EXCHANGE, RabbitMQConfig.LIKE_ADD_KEY,
                    new LikeMQMessage(userId, noteId));
        }
    }

    @Override
    public Long getLikeCount(Long noteId) {
        String countStr = redisTemplate.opsForValue().get(SystemConstants.NOTE_LIKE_COUNT_KEY + noteId);
        if (countStr != null) return Long.parseLong(countStr);
        Note note = getById(noteId);
        if (note == null) return 0L;
        long count = note.getLikeCount();
        redisTemplate.opsForValue().set(SystemConstants.NOTE_LIKE_COUNT_KEY + noteId, String.valueOf(count));
        return count;
    }

    // 私有方法：Entity → VO，处理图片字段
    private NoteVO convertToVO(Note note) {
        NoteVO vo = new NoteVO();
        BeanUtil.copyProperties(note, vo);
        if (note.getImages() != null && !note.getImages().isBlank()) {
            vo.setImages(Arrays.asList(note.getImages().split(",")));
        } else {
            vo.setImages(Collections.emptyList());
        }
        return vo;
    }
}