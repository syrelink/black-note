package com.syr.service.Impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.json.JSONUtil;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.exception.BusinessException;
import com.syr.dto.NotePublishDTO;
import com.syr.entity.Note;
import com.syr.entity.User;
import com.syr.mapper.NoteMapper;
import com.syr.mapper.UserMapper;
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
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;
import com.syr.utils.SystemConstants;
import com.syr.config.RabbitMQConfig;

@Slf4j
@Service
@RequiredArgsConstructor
public class NoteServiceImpl extends ServiceImpl<NoteMapper, Note> implements NoteService {

    private final StringRedisTemplate redisTemplate;
    private final RabbitTemplate      rabbitTemplate;
    private final UserMapper          userMapper;   // ← 新增，用于查询作者信息


    @Override
    public void publish(NotePublishDTO dto) {
        Long userId = UserHolder.getUserId();
        if (userId == null) throw new BusinessException(401, "未登录，请先登录");

        Note note = new Note();
        note.setUserId(userId);
        note.setTitle(dto.getTitle());
        note.setContent(dto.getContent());
        if (dto.getImages() != null && !dto.getImages().isEmpty()) {
            note.setImages(String.join(",", dto.getImages()));
        }
        save(note);
        rabbitTemplate.convertAndSend(RabbitMQConfig.FEED_EXCHANGE, RabbitMQConfig.FEED_PUSH_KEY, note.getId());
        // 新增：异步同步到向量库
        rabbitTemplate.convertAndSend(RabbitMQConfig.NOTE_SYNC_EXCHANGE, RabbitMQConfig.NOTE_SYNC_KEY, note.getId().toString());
    }

    @Override
    public NoteVO getNoteById(Long id) {
        String key  = SystemConstants.NOTE_DETAIL_KEY + id;
        String json = redisTemplate.opsForValue().get(key);

        if (json != null) {
            if (SystemConstants.CACHE_NULL_VALUE.equals(json)) throw new BusinessException(404, "笔记不存在");
            NoteVO vo = JSONUtil.toBean(json, NoteVO.class);
            // 点赞数从 Redis 实时读取
            fillLikeInfo(vo);
            return vo;
        }
       // redis 没有再查询数据库
        Note note = getById(id);
        if (note == null) {
            // 数据库没有，就保存空值
            redisTemplate.opsForValue().set(key, SystemConstants.CACHE_NULL_VALUE,
                    SystemConstants.CACHE_NULL_TTL, TimeUnit.MINUTES);
            return null;
        }

        // 查到了数据，就转为vo，并更新缓存的ttl
        NoteVO vo = convertBatch(Collections.singletonList(note)).get(0);
        redisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(vo),
                SystemConstants.CACHE_TTL, TimeUnit.MINUTES);
        // 自动填充点赞和点赞数
        fillLikeInfo(vo);
        return vo;
    }

    @Override
    @Transactional
    public void deleteNote(Long id) {
        Long userId = UserHolder.getUserId();

        Note note = getById(id);
        if (note == null) {
            throw new BusinessException(404, "笔记不存在");
        }
        if (!note.getUserId().equals(userId)) {
            throw new BusinessException(403, "无权删除此笔记");
        }
        removeById(id);

        String key = SystemConstants.NOTE_DETAIL_KEY + id;
        // 删除缓存的时候，记得捕获异常，可能会删除失败造成数据不一致问题
        try {
            redisTemplate.delete(key);
        } catch (Exception e) {
            log.error("删除缓存失败，发MQ补偿，key={}", key, e);
            rabbitTemplate.convertAndSend(RabbitMQConfig.CACHE_EXCHANGE, RabbitMQConfig.CACHE_DELETE_KEY, key);
        }
        // 新增：从向量库删除
        rabbitTemplate.convertAndSend(RabbitMQConfig.NOTE_SYNC_EXCHANGE, RabbitMQConfig.NOTE_SYNC_KEY, "-" + id);
    }

    @Override
    public List<NoteVO> listByUser(Long userId) {
        List<Note> notes = lambdaQuery()
                .eq(Note::getUserId, userId)
                .eq(Note::getIsDeleted, 0)
                .orderByDesc(Note::getCreatedAt)
                .list();

        if (notes.isEmpty()) return Collections.emptyList();
        return convertBatch(notes);
    }

    // ── 点赞 / 取消点赞 ──
    // 用 Redis Set 记录谁点过赞，用 Redis String 记录点赞数
    // 通过 MQ 异步同步到数据库，保证高性能
    @Override
    public void like(Long noteId) {
        Long userId = UserHolder.getUserId();
        if (userId == null) throw new BusinessException(401, "未登录");

        // 笔记的用户点赞集合（去重）
        String likeSetKey   = SystemConstants.NOTE_LIKE_SET_KEY   + noteId;
        // 点赞数量（计数）
        String likeCountKey = SystemConstants.NOTE_LIKE_COUNT_KEY + noteId;

        // 初始化点赞数（如果Redis里没有，从数据库读）
        initLikeCountIfAbsent(noteId, likeCountKey);
        // 查询当前用户是否点赞了笔记
        Boolean isMember = redisTemplate.opsForSet().isMember(likeSetKey, userId.toString());

        if (Boolean.TRUE.equals(isMember)) {
            // 已点赞 → 取消
            redisTemplate.opsForSet().remove(likeSetKey, userId.toString());
            redisTemplate.opsForValue().decrement(likeCountKey);
            rabbitTemplate.convertAndSend(RabbitMQConfig.LIKE_EXCHANGE, RabbitMQConfig.LIKE_CANCEL_KEY,
                    new LikeMQMessage(userId, noteId));
        } else {
            // 未点赞 → 点赞
            redisTemplate.opsForSet().add(likeSetKey, userId.toString());
            redisTemplate.opsForValue().increment(likeCountKey);
            rabbitTemplate.convertAndSend(RabbitMQConfig.LIKE_EXCHANGE, RabbitMQConfig.LIKE_ADD_KEY,
                    new LikeMQMessage(userId, noteId));
        }
    }

    @Override
    public Long getLikeCount(Long noteId) {
        String likeCountKey = SystemConstants.NOTE_LIKE_COUNT_KEY + noteId;
        initLikeCountIfAbsent(noteId, likeCountKey);
        String countStr = redisTemplate.opsForValue().get(likeCountKey);
        return countStr != null ? Long.parseLong(countStr) : 0L;
    }

    @Override
    public Boolean isLiked(Long noteId) {
        Long userId = UserHolder.getUserId();
        if (userId == null) return false;
        String likeSetKey = SystemConstants.NOTE_LIKE_SET_KEY + noteId;
        return Boolean.TRUE.equals(redisTemplate.opsForSet().isMember(likeSetKey, userId.toString()));
    }

    // ── 首页公开笔记列表 ──
    @Override
    public List<NoteVO> noteList(Integer page, Integer size) {
        List<Note> notes = lambdaQuery()
                .eq(Note::getIsDeleted, 0)
                .orderByDesc(Note::getCreatedAt)
                .last("limit " + (page - 1) * size + "," + size)
                .list();

        if (notes.isEmpty()) return Collections.emptyList();
        return convertBatch(notes);
    }

    @Override
    @Transactional
    public void updateNote(Long id, NotePublishDTO dto) {
        Long userId = UserHolder.getUserId();
        Note note = getById(id);
        if (note == null) throw new BusinessException(404, "笔记不存在");
        if (!note.getUserId().equals(userId)) throw new BusinessException(403, "无权编辑此笔记");

        note.setTitle(dto.getTitle());
        note.setContent(dto.getContent());
        if (dto.getImages() != null && !dto.getImages().isEmpty()) {
            note.setImages(String.join(",", dto.getImages()));
        } else {
            note.setImages(null);
        }
        updateById(note);

        // 删除缓存
        String key = SystemConstants.NOTE_DETAIL_KEY + id;
        try {
            redisTemplate.delete(key);
        } catch (Exception e) {
            log.error("删除缓存失败，key={}", key, e);
            rabbitTemplate.convertAndSend(RabbitMQConfig.CACHE_EXCHANGE, RabbitMQConfig.CACHE_DELETE_KEY, key);
        }
    }

    /**
     * 批量转VO（核心方法）
     * 解决N+1问题：2次SQL查所有数据
     */
    private List<NoteVO> convertBatch(List<Note> notes) {

        // 1. 基本字段转换
        List<NoteVO> voList = notes.stream().map(note -> {
            NoteVO vo = new NoteVO();
            BeanUtil.copyProperties(note, vo);
            // 图片处理：逗号字符串 → List
            if (note.getImages() != null && !note.getImages().isBlank()) {
                vo.setImages(Arrays.asList(note.getImages().split(",")));
            } else {
                vo.setImages(Collections.emptyList());
            }
            return vo;
        }).collect(Collectors.toList());

        // 2. 批量查作者（1次SQL，解决N+1）
        List<Long> userIds = notes.stream()
                .map(Note::getUserId)
                .distinct()
                .collect(Collectors.toList());

        Map<Long, User> userMap = userMapper.selectBatchIds(userIds)
                .stream()
                .collect(Collectors.toMap(User::getId, u -> u));

        // 3. 填充作者信息 + 点赞信息
        voList.forEach(vo -> {
            // 作者信息
            User author = userMap.get(vo.getUserId());
            if (author != null) {
                vo.setAuthorName(author.getNickname() != null
                        ? author.getNickname()
                        : author.getUsername());
                vo.setAuthorAvatar(author.getAvatar());
            }
            // 点赞信息
            fillLikeInfo(vo);
        });

        return voList;
    }

    private void fillLikeInfo(NoteVO vo) {
        Long noteId = vo.getId();
        Long userId = UserHolder.getUserId();

        // 点赞数从Redis取
        String countKey = SystemConstants.NOTE_LIKE_COUNT_KEY + noteId;
        String count = redisTemplate.opsForValue().get(countKey);
        if (count != null) {
            // Redis有点赞数，用Redis的（最新的）parseInt把字符串转成数字
            vo.setLikeCount(Integer.parseInt(count));
        } else {
            // Redis没有，用数据库查出来的（原来的）
            vo.setLikeCount(vo.getLikeCount());
        }

        // 是否点赞从Redis Set取（未登录默认false）
        if (userId != null) {
            String setKey = SystemConstants.NOTE_LIKE_SET_KEY + noteId;
            Boolean isLiked = redisTemplate.opsForSet()
                    .isMember(setKey, userId.toString());
            vo.setIsLiked(Boolean.TRUE.equals(isLiked));
        } else {
            vo.setIsLiked(false);
        }
    }

    // 如果 Redis 里没有点赞数，从数据库初始化
    private void initLikeCountIfAbsent(Long noteId, String likeCountKey) {
        if (!Boolean.TRUE.equals(redisTemplate.hasKey(likeCountKey))) {
            Note note = getById(noteId);
            if (note == null) throw new BusinessException(404, "笔记不存在");
            // 删掉多余的 if (note != null)，直接写
            redisTemplate.opsForValue().set(likeCountKey,
                    String.valueOf(note.getLikeCount()),
                    7, TimeUnit.DAYS);
        }
    }
}