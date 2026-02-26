package com.syr.config;


import org.springframework.amqp.core.*;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class RabbitMQConfig {

    // 点赞
    public static final String LIKE_EXCHANGE     = "like.exchange";
    public static final String LIKE_ADD_QUEUE    = "like.add.queue";
    public static final String LIKE_CANCEL_QUEUE = "like.cancel.queue";
    public static final String LIKE_ADD_KEY      = "like.add";
    public static final String LIKE_CANCEL_KEY   = "like.cancel";

    // Feed推送
    public static final String FEED_EXCHANGE   = "feed.exchange";
    public static final String FEED_PUSH_QUEUE = "feed.push.queue";
    public static final String FEED_PUSH_KEY   = "feed.push";

    // 缓存补偿
    public static final String CACHE_EXCHANGE     = "cache.exchange";
    public static final String CACHE_DELETE_QUEUE = "cache.delete.queue";
    public static final String CACHE_DELETE_KEY   = "cache.delete";

    // Exchange
    @Bean public DirectExchange likeExchange()  { return new DirectExchange(LIKE_EXCHANGE);  }
    @Bean public DirectExchange feedExchange()  { return new DirectExchange(FEED_EXCHANGE);  }
    @Bean public DirectExchange cacheExchange() { return new DirectExchange(CACHE_EXCHANGE); }

    // Queue
    @Bean public Queue likeAddQueue()     { return new Queue(LIKE_ADD_QUEUE);     }
    @Bean public Queue likeCancelQueue()  { return new Queue(LIKE_CANCEL_QUEUE);  }
    @Bean public Queue feedPushQueue()    { return new Queue(FEED_PUSH_QUEUE);    }
    @Bean public Queue cacheDeleteQueue() { return new Queue(CACHE_DELETE_QUEUE); }

    // Binding
    @Bean
    public Binding likeAddBinding() {
        return BindingBuilder.bind(likeAddQueue()).to(likeExchange()).with(LIKE_ADD_KEY);
    }
    @Bean
    public Binding likeCancelBinding() {
        return BindingBuilder.bind(likeCancelQueue()).to(likeExchange()).with(LIKE_CANCEL_KEY);
    }
    @Bean
    public Binding feedPushBinding() {
        return BindingBuilder.bind(feedPushQueue()).to(feedExchange()).with(FEED_PUSH_KEY);
    }
    @Bean
    public Binding cacheDeleteBinding() {
        return BindingBuilder.bind(cacheDeleteQueue()).to(cacheExchange()).with(CACHE_DELETE_KEY);
    }

    // 消息序列化为JSON
    @Bean
    public MessageConverter messageConverter() {
        return new Jackson2JsonMessageConverter();
    }
}