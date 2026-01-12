package com.syr.utils;

public interface ILock {
    boolean tryLock(long timeoutSec);

    void unlock();
}
