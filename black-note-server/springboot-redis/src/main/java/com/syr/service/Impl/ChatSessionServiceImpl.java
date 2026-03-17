package com.syr.service.Impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.entity.ChatSession;
import com.syr.mapper.ChatSessionMapper;
import com.syr.service.ChatSessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

// service/impl/ChatSessionServiceImpl.java
@Service
@RequiredArgsConstructor
public class ChatSessionServiceImpl implements ChatSessionService {

    private final ChatSessionMapper sessionMapper;

    @Override
    public List<ChatSession> getByUserId(Long userId) {
        return sessionMapper.selectList(
                new LambdaQueryWrapper<ChatSession>()
                        .eq(ChatSession::getUserId, userId)
                        .orderByDesc(ChatSession::getUpdatedAt)
        );
    }

    @Override
    public void upsert(String sessionId, Long userId, String title) {
        ChatSession existing = sessionMapper.selectById(sessionId);
        if (existing == null) {
            // 新建
            ChatSession s = new ChatSession();
            s.setId(sessionId);
            s.setUserId(userId);
            s.setTitle(title);
            sessionMapper.insert(s);
        } else {
            // 更新标题
            existing.setTitle(title);
            sessionMapper.updateById(existing);
        }
    }

    @Override
    public void delete(String sessionId, Long userId) {
        sessionMapper.delete(
                new LambdaQueryWrapper<ChatSession>()
                        .eq(ChatSession::getId, sessionId)
                        .eq(ChatSession::getUserId, userId)
        );
    }
}