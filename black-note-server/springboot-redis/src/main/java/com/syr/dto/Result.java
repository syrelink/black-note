package com.syr.dto;
import lombok.Data;


@Data

public class Result<T> {
    private Integer code;
    private String message;
    private T data;

    // 成功
    public static <T> Result<T> success(T data) {
        Result<T> r = new Result<>();
        r.code = 200;
        r.message = "success";
        r.data = data;
        return r;
    }
    public static <T> Result<T> success() {
        return success(null);
    }
    // 失败
    public static <T> Result<T> fail(String message) {
        Result<T> r = new Result<>();
        r.code = 500;
        r.message = message;
        return r;
    }

    // 自定义状态码
    public static <T> Result<T> fail(Integer code, String message) {
        Result<T> r = new Result<>();
        r.code = code;
        r.message = message;
        return r;
    }
}
