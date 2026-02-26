package com.syr.vo;

import lombok.Data;
import java.time.LocalDateTime;

@Data
public class UserVO {

    private Long id;

    private String username;

    private String nickname;

    private String avatar;

    private LocalDateTime createdAt;

    // 注意：password 字段不在VO里，永远不返回给前端
}