package com.syr.dto;

import lombok.Data;

@Data
public class UserDTO {
    private Long id;
    private String nickName;
    private String icon;

    // 手动添加 getter/setter 方法以防 Lombok 失效
    public Long getId() {
        return id;
    }
}
