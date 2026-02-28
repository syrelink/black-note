package com.syr.vo;

import lombok.Data;

@Data
public class LoginVO {
    private String token;      // 登录凭证
    private Long   id;         // 用户id
    private String username;   // 用户名
    private String nickname;   // 昵称
    private String avatar;     // 头像
}