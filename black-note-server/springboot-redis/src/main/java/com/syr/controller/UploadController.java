package com.syr.controller;

import cn.hutool.core.io.FileUtil;
import cn.hutool.core.util.StrUtil;
import com.syr.dto.Result;
import com.syr.utils.SystemConstants;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.util.UUID;
@Tag(name = "文件上传管理", description = "处理博客图片上传和删除功能")
@Slf4j
@RestController
@RequestMapping("upload")
public class UploadController {
    @Operation(summary = "上传博客图片", description = "上传博客文章中使用的图片文件")
    @PostMapping
    public Result uploadImage(
            @Parameter(name = "file", description = "要上传的图片文件", required = true)
            @RequestParam("file") MultipartFile image) {
        try {
            String originalFilename = image.getOriginalFilename();
            String fileName =  createNewFileName(originalFilename);
            image.transferTo(new File(SystemConstants.IMAGE_UPLOAD_DIR, fileName));
            log.debug("文件上传成功，{}",fileName);
            return Result.ok();
        } catch (IOException e) {
            throw new RuntimeException("上传文件失败",e);
        }
    }
    @Operation(summary = "删除博客图片", description = "删除指定的博客图片文件")
    @Parameter(name = "filename", description = "要删除的图片文件名", required = true, example = "blogs/1/2/uuid.jpg")
    @GetMapping("/blog/delete")
    public Result deleteBlogImg(@RequestParam("filename") String filename) {
        File file = new File(SystemConstants.IMAGE_UPLOAD_DIR, filename);
        if (file.isDirectory()) {
            return Result.fail("错误的文件名称");
        }
        FileUtil.del(file);
        return Result.ok();
    }

    private String createNewFileName(String originalFilename) {
        // 获取后缀
        String suffix = StrUtil.subAfter(originalFilename, ".", true);
        // 生成目录
        String name = UUID.randomUUID().toString();
        int hash = name.hashCode();
        int d1 = hash & 0xF;
        int d2 = (hash >> 4) & 0xF;
        // 判断目录是否存在
        File dir = new File(SystemConstants.IMAGE_UPLOAD_DIR, StrUtil.format("/blogs/{}/{}", d1, d2));
        if (!dir.exists()) {
            dir.mkdirs();
        }
        // 生成文件名
        return StrUtil.format("/blogs/{}/{}/{}.{}", d1, d2, name, suffix);
    }
}
