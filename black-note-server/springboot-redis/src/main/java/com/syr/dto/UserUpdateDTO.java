package com.syr.dto;

import lombok.Data;
import org.hibernate.validator.constraints.Length;

@Data
public class UserUpdateDTO {
    @Length(max = 12, message = "昵称不能超过12字")
    private String nickname;
    private String avatar;
}