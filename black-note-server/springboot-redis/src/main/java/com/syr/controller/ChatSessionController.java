package com.syr.controller;

import com.syr.dto.Result;
import com.syr.entity.ChatSession;
import com.syr.service.ChatSessionService;
import com.syr.utils.UserHolder;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

// controller/ChatSessionController.java
@RestController
@RequestMapping("/chat/sessions")
@RequiredArgsConstructor
public class ChatSessionController {

    private final ChatSessionService sessionService;  // ← 注入 Service

    @GetMapping
    public Result<List<ChatSession>> getSessions() {
        Long userId = UserHolder.getUserId();
        return Result.success(sessionService.getByUserId(userId));
    }

    @PostMapping("/{sessionId}")
    public Result<Void> upsertSession(
            @PathVariable String sessionId,
            @RequestBody Map<String, String> body
    ) {
        Long userId = UserHolder.getUserId();
        String title = body.getOrDefault("title", "新对话");
        sessionService.upsert(sessionId, userId, title);
        return Result.success();
    }

    @DeleteMapping("/{sessionId}")
    public Result<Void> deleteSession(@PathVariable String sessionId) {
        Long userId = UserHolder.getUserId();
        sessionService.delete(sessionId, userId);
        return Result.success();
    }
}