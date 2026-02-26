package com.syr.utils;

public class UserHolder {

    private static final ThreadLocal<Long> tl = new ThreadLocal<>();

    public static void setUserId(Long id) {
        tl.set(id);
    }

    public static Long getUserId() {
        return tl.get();
    }

    // 请求结束后必须清除，防止内存泄漏
    public static void remove() {
        tl.remove();
    }
}
