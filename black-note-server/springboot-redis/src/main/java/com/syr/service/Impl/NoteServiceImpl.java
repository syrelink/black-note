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

    // ── 发布笔记 ──
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
    }

    // ── 查询笔记详情（带缓存）──
    @Override
    public NoteVO getNoteById(Long id) {
        String key  = SystemConstants.NOTE_DETAIL_KEY + id;
        String json = redisTemplate.opsForValue().get(key);

        if (json != null) {
            if (SystemConstants.CACHE_NULL_VALUE.equals(json)) return null;
            NoteVO vo = JSONUtil.toBean(json, NoteVO.class);
            // 点赞数从 Redis 实时读取，不走缓存（保证准确）
            fillLikeCount(vo);
            fillIsLiked(vo);
            return vo;
        }

        Note note = getById(id);
        if (note == null) {
            redisTemplate.opsForValue().set(key, SystemConstants.CACHE_NULL_VALUE,
                    SystemConstants.CACHE_NULL_TTL, TimeUnit.MINUTES);
            return null;
        }

        NoteVO vo = convertToVO(note);
        redisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(vo),
                SystemConstants.CACHE_TTL, TimeUnit.MINUTES);
        fillLikeCount(vo);
        fillIsLiked(vo);
        return vo;
    }

    // ── 删除笔记 ──
    @Override
    @Transactional
    public void deleteNote(Long id) {
        Long userId = UserHolder.getUserId();
        Note note   = getById(id);
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

    // ── 查询某用户的笔记列表 ──
    @Override
    public List<NoteVO> listByUser(Long userId) {
        List<Note> notes = lambdaQuery()
                .eq(Note::getUserId, userId)
                .orderByDesc(Note::getCreatedAt)
                .list();
        if (notes == null || notes.isEmpty()) return Collections.emptyList();
        return notes.stream()
                .map(this::convertToVO)
                .peek(this::fillLikeCount)
                .peek(this::fillIsLiked)
                .collect(Collectors.toList());
    }

    // ── 点赞 / 取消点赞 ──
    // 用 Redis Set 记录谁点过赞，用 Redis String 记录点赞数
    // 通过 MQ 异步同步到数据库，保证高性能
    @Override
    public void like(Long noteId) {
        Long userId = UserHolder.getUserId();
        if (userId == null) throw new BusinessException(401, "未登录");

        String likeSetKey   = SystemConstants.NOTE_LIKE_SET_KEY   + noteId;
        String likeCountKey = SystemConstants.NOTE_LIKE_COUNT_KEY + noteId;

        // 初始化点赞数（如果Redis里没有，从数据库读）
        initLikeCountIfAbsent(noteId, likeCountKey);

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

    // ── 查询点赞数 ──
    @Override
    public Long getLikeCount(Long noteId) {
        String likeCountKey = SystemConstants.NOTE_LIKE_COUNT_KEY + noteId;
        initLikeCountIfAbsent(noteId, likeCountKey);
        String countStr = redisTemplate.opsForValue().get(likeCountKey);
        return countStr != null ? Long.parseLong(countStr) : 0L;
    }

    // ── 查询当前用户是否点赞了某笔记 ──
    // 新增接口：前端刷新后调用，恢复点赞状态
    @Override
    public Boolean isLiked(Long noteId) {
        Long userId = UserHolder.getUserId();
        System.out.println("为什么*************");
        if (userId == null) return false;
        String likeSetKey = SystemConstants.NOTE_LIKE_SET_KEY + noteId;
        return Boolean.TRUE.equals(redisTemplate.opsForSet().isMember(likeSetKey, userId.toString()));
    }

    // ── 全站公开笔记列表（首页） ──
    @Override
    public List<NoteVO> noteList(Integer page, Integer size) {
        List<Note> notes = lambdaQuery()
                .orderByDesc(Note::getCreatedAt)
                .last("limit " + ((page - 1) * size) + "," + size)
                .list();
        if (notes == null || notes.isEmpty()) return Collections.emptyList();
        return notes.stream()
                .map(this::convertToVO)
                .peek(this::fillLikeCount)
                .peek(this::fillIsLiked)
                .collect(Collectors.toList());
    }

    // ══════════════════════════════
    //  私有工具方法
    // ══════════════════════════════

    // Entity → VO，补充作者信息 + 处理图片字段
    private NoteVO convertToVO(Note note) {
        NoteVO vo = new NoteVO();
        BeanUtil.copyProperties(note, vo);

        // 图片：逗号字符串 → List
        if (note.getImages() != null && !note.getImages().isBlank()) {
            vo.setImages(Arrays.asList(note.getImages().split(",")));
        } else {
            vo.setImages(Collections.emptyList());
        }

        // 作者信息：从数据库查（生产环境可加缓存）
        User author = userMapper.selectById(note.getUserId());
        if (author != null) {
            vo.setAuthorName(author.getNickname() != null ? author.getNickname() : author.getUsername());
            vo.setAuthorAvatar(author.getAvatar());
        }

        return vo;
    }

    // 从 Redis 实时填充点赞数（覆盖缓存里的旧值）
    private void fillLikeCount(NoteVO vo) {
        if (vo == null) return;
        String countStr = redisTemplate.opsForValue().get(SystemConstants.NOTE_LIKE_COUNT_KEY + vo.getId());
        if (countStr != null) {
            vo.setLikeCount(Integer.parseInt(countStr));
        }
    }
    // 填充当前登录用户是否点赞
    private void fillIsLiked(NoteVO vo) {
        if (vo == null) return;
        Long userId = UserHolder.getUserId();
        // 未登录，一律视为未点赞
        if (userId == null) {
            vo.setLiked(false);
            return;
        }
        String likeSetKey = SystemConstants.NOTE_LIKE_SET_KEY + vo.getId();
        boolean liked = Boolean.TRUE.equals(
                redisTemplate.opsForSet().isMember(likeSetKey, userId.toString())
        );
        vo.setLiked(liked);
    }
    // 如果 Redis 里没有点赞数，从数据库初始化
    private void initLikeCountIfAbsent(Long noteId, String likeCountKey) {
        if (!Boolean.TRUE.equals(redisTemplate.hasKey(likeCountKey))) {
            Note note = getById(noteId);
            if (note != null) {
                redisTemplate.opsForValue().set(likeCountKey,
                        String.valueOf(note.getLikeCount()),
                        7, TimeUnit.DAYS);
            }
        }
    }
}