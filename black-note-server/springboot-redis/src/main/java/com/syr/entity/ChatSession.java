package com.syr.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("chat_sessions")
public class ChatSession {
    private String id;
    private Long   userId;
    private String title;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}