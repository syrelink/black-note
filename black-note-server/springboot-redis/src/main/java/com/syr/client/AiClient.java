package com.syr.client;

        import lombok.extern.slf4j.Slf4j;
        import org.springframework.stereotype.Component;
        import org.springframework.web.reactive.function.client.WebClient;

@Slf4j
@Component
public class AiClient {

    private final WebClient webClient = WebClient.builder()
            .baseUrl("http://localhost:8001")
            .build();

    /**
     * 笔记发布后同步到向量库
     * 异步调用，不阻塞主流程
     */
    public void syncNote(Long noteId) {
        webClient.post()
                .uri("/ai/sync_note")
                .bodyValue(java.util.Map.of("note_id", noteId))
                .retrieve()
                .bodyToMono(String.class)
                .subscribe(
                        res -> log.info("笔记{}向量化成功", noteId),
                        err -> log.error("笔记{}向量化失败: {}", noteId, err.getMessage())
                );
    }

    /**
     * 笔记删除后从向量库移除
     */
    public void deleteNote(Long noteId) {
        webClient.post()
                .uri("/ai/delete_note")
                .bodyValue(java.util.Map.of("note_id", noteId))
                .retrieve()
                .bodyToMono(String.class)
                .subscribe(
                        res -> log.info("笔记{}已从向量库删除", noteId),
                        err -> log.error("笔记{}向量库删除失败: {}", noteId, err.getMessage())
                );
    }
}