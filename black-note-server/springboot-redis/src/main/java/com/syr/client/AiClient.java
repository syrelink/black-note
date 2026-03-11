package com.syr.client;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.Map;

@Slf4j
@Component
public class AiClient {

    private final RestClient restClient = RestClient.builder()
            .baseUrl("http://localhost:8001")
            .build();

    public void syncNote(Long noteId) {
        new Thread(() -> {
            try {
                restClient.post()
                        .uri("/ai/sync_note")
                        .contentType(MediaType.APPLICATION_JSON)
                        .body("{\"note_id\":" + noteId + "}")
                        .retrieve()
                        .toBodilessEntity();
                log.info("笔记{}向量化成功", noteId);
            } catch (Exception e) {
                log.error("笔记{}向量化失败: {}", noteId, e.getMessage());
            }
        }).start();
    }

    public void deleteNote(Long noteId) {
        new Thread(() -> {
            try {
                restClient.post()
                        .uri("/ai/delete_note")
                        .contentType(MediaType.APPLICATION_JSON)
                        .body("{\"note_id\":" + noteId + "}")
                        .retrieve()
                        .toBodilessEntity();
                log.info("笔记{}已从向量库删除", noteId);
            } catch (Exception e) {
                log.error("笔记{}向量库删除失败: {}", noteId, e.getMessage());
            }
        }).start();
    }
}