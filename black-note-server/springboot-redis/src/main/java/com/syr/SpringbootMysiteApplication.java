package com.syr;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.EnableAspectJAutoProxy;

@EnableAspectJAutoProxy(exposeProxy = true)
@SpringBootApplication
@MapperScan("com.syr.mapper")
public class SpringbootMysiteApplication {

    public static void main(String[] args) {
        SpringApplication.run(SpringbootMysiteApplication.class, args);
    }

}
