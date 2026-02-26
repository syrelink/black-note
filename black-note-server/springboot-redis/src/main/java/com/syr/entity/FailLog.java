package com.syr.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;

@Data
@TableName("fail_log")
public class FailLog {

    @TableId(type = IdType.AUTO)
    private Long id;

    // 失败类型枚举值：CACHE_DELETE / LIKE_SYNC
    private String type;

    private String content;

    private Integer retryCount;

    // 0=待处理 1=已处理
    private Integer status;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}