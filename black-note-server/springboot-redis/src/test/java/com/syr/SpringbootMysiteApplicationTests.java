package com.syr;

import com.syr.utils.RedisIdWorker;
import jakarta.annotation.Resource;
import org.springframework.boot.test.context.SpringBootTest;


@SpringBootTest
class SpringbootMysiteApplicationTests {
    @Resource
    private RedisIdWorker redisIdWorker;


}
