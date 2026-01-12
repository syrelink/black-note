package com.syr.exception;

import lombok.Getter;

/**
 * 业务异常类
 * Service层抛出此异常，由GlobalExceptionHandler统一捕获并转换为Result.fail()
 */
@Getter
public class BusinessException extends RuntimeException {

    public BusinessException(String message) {
        super(message);
    }
}
