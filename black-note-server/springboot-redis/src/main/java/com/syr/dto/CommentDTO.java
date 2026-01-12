package com.syr.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
public class CommentDTO {
    @Schema(description = "评论内容")
    private String content;

    @Schema(description = "父评论ID (如果是直接评论笔记，传0或不传)")
    private Long parentId;

    @Schema(description = "被回复人的ID (可选，用于显示回复了谁)")
    private Long answerId;
}