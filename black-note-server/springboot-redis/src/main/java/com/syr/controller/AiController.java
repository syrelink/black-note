package com.syr.controller;

import com.syr.utils.UserHolder;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;

@RestController
@RequestMapping("/ai")
@RequiredArgsConstructor
public class AiController {

    private final WebClient webClient = WebClient.builder()
            .baseUrl("http://localhost:8001")
            .build();

    /**
     * RAG问答，流式返回
     * 前端用EventSource接收
     */
    @PostMapping(value = "/chat", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<String> chat(@RequestBody java.util.Map<String, String> body) {
        Long userId      = UserHolder.getUserId();
        String question  = body.get("question");
        String sessionId = body.getOrDefault("session_id", "default");

        return webClient.post()
                .uri("/ai/chat")
                .header("X-User-Id", userId.toString())
                .header("Content-Type", "application/json")
                .bodyValue(java.util.Map.of(
                        "question",   question,
                        "session_id", userId + "_" + sessionId
                ))
                .retrieve()
                .bodyToFlux(String.class);
    }

    /**
     * 语义搜索，返回相关笔记列表
     */
    @GetMapping("/search")
    public reactor.core.publisher.Mono<String> search(@RequestParam String q) {
        Long userId = UserHolder.getUserId();

        return webClient.get()
                .uri("/ai/search?q=" + q)
                .header("X-User-Id", userId.toString())
                .retrieve()
                .bodyToMono(String.class);
    }
}