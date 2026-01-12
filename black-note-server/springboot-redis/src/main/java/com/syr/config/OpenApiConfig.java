package com.syr.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.ExternalDocumentation;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

    @Bean
    public OpenAPI springShopOpenAPI() {
        return new OpenAPI()
                .info(new Info().title("小黑书 API")
                        .description("基于 Spring Boot 3 + Redis 的高性能图文博客后端")
                        .version("v1.0.0")
                        .contact(new Contact().name("syr").email("your-email@example.com")))
                .externalDocs(new ExternalDocumentation()
                        .description("项目 GitHub 地址")
                        .url("https://github.com/syrelink/JavaProject-mysite"));
    }
}