package com.syr.service;

import org.springframework.web.multipart.MultipartFile;

public interface FileService {
    /**
     * 上传图片到MinIO，返回可访问的URL
     */
    String uploadImage(MultipartFile file);
}