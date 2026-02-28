package com.syr.dto;
import lombok.Data;


@Data
public class Result<T> {

    private Integer code;
    private String message;
    private T data;

    // ======= 成功 =======
    public static <T> Result<T> success(T data) {
        Result<T> r = new Result<>();
        r.code = 200;
        r.message = "OK";
        r.data = data;
        return r;
    }

    public static <T> Result<T> success() {
        return success(null);
    }

    // ======= 通用失败（500）=======
    public static <T> Result<T> fail(String message) {
        return fail(500, message);
    }

    // ======= 自定义状态码 =======
    public static <T> Result<T> fail(Integer code, String message) {
        Result<T> r = new Result<>();
        r.code = code;
        r.message = message;
        r.data = null;
        return r;
    }
}
