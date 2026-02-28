package com.syr.vo;

import lombok.Data;
import java.time.LocalDateTime;
import java.util.List;

@Data
public class NoteVO {

    private Long id;

    private Long userId;
    private String nickname;
    private String avatar;
    private String title;

    private String content;
    private List<String> images;  // 返回给前端时拆成列表
    private Integer likeCount;

    // 当前登录用户是否点赞了这篇笔记（从Redis Set判断后填入）
    private Boolean liked;

    // 作者信息（避免前端再发一次请求）
    private String authorName;

    private String authorAvatar;

    private LocalDateTime createdAt;
}