package com.syr.service;

import com.syr.entity.ChatSession;

import java.util.List;

// service/ChatSessionService.java
public interface ChatSessionService {
    List<ChatSession> getByUserId(Long userId);
    void upsert(String sessionId, Long userId, String title);
    void delete(String sessionId, Long userId);
}