package com.syr.vo;

import lombok.Data;
import java.time.LocalDateTime;
import java.util.List;

@Data
public class NoteVO {

    private Long id;
    private String title;

    private String content;
    private List<String> images;
    private Integer likeCount;

    private Boolean isLiked;

    // 作者信息（从User表填充）
    private Long   userId;
    private String authorName;      // 作者昵称
    private String authorAvatar;    // 作者头像

    private LocalDateTime createdAt;
}