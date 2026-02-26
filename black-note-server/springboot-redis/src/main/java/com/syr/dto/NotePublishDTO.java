package com.syr.dto;


import lombok.Data;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.util.List;

@Data
public class NotePublishDTO {

    @NotBlank(message = "标题不能为空")
    @Size(max = 24, message = "标题最多24个字符")
    private String title;

    @NotBlank(message = "内容不能为空")
    private String content;

    // 前端先调上传接口拿到URL列表，发布时一起带过来
    private List<String> images;
}