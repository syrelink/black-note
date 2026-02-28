package com.syr.service.Impl;

import cn.hutool.core.lang.UUID;
import com.syr.exception.BusinessException;
import com.syr.service.FileService;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

@Slf4j
@Service
@RequiredArgsConstructor
public class FileServiceImpl implements FileService {

    private final MinioClient minioClient;

    @Value("${minio.bucket}")
    private String bucket;

    @Value("${minio.endpoint}")
    private String endpoint;

    @Override
    public String uploadImage(MultipartFile file) {

        // 1. 校验文件不能为空
        if (file == null || file.isEmpty()) {
            throw new BusinessException(400, "文件不能为空");
        }

        // 2. 校验必须是图片类型
        // getContentType()返回的是MIME类型，图片都是 image/jpeg image/png 等
        String contentType = file.getContentType();
        if (contentType == null || !contentType.startsWith("image/")) {
            throw new BusinessException(400, "只能上传图片文件");
        }

        // 3. 生成唯一文件名，防止重名覆盖
        // 原始文件名可能是 "我的照片.jpg"，取后缀 ".jpg"
        String originalName = file.getOriginalFilename();
        String suffix = (originalName != null && originalName.contains("."))
                ? originalName.substring(originalName.lastIndexOf("."))
                : ".jpg";
        // 最终文件名如：a1b2c3d4e5f6.jpg
        String fileName = UUID.randomUUID().toString(true) + suffix;

        // 4. 上传到MinIO
        try {
            minioClient.putObject(
                    PutObjectArgs.builder()
                            .bucket(bucket)          // 存到哪个桶
                            .object(fileName)        // 文件名
                            .stream(
                                    file.getInputStream(),  // 文件流
                                    file.getSize(),         // 文件大小
                                    -1                      // 固定写-1即可
                            )
                            .contentType(contentType)   // 文件类型
                            .build()
            );
        } catch (Exception e) {
            log.error("上传图片到MinIO失败", e);
            throw new BusinessException("图片上传失败，请重试");
        }

        // 5. 拼接并返回可访问的URL
        // 格式：http://localhost:9000/syr/a1b2c3d4.jpg
        String url = endpoint + "/" + bucket + "/" + fileName;
        log.info("图片上传成功，url={}", url);
        return url;
    }
}