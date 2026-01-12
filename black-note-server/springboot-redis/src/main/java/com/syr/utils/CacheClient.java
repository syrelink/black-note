package com.syr.utils;

import cn.hutool.core.util.BooleanUtil;
import cn.hutool.core.util.StrUtil;
import cn.hutool.json.JSONObject;
import cn.hutool.json.JSONUtil;
import com.syr.entity.Shop;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;

import static com.syr.utils.RedisConstants.*;

@Slf4j
@Component
public class CacheClient {
    private StringRedisTemplate stringRedisTemplate;

    public CacheClient(StringRedisTemplate stringRedisTemplate) {
        this.stringRedisTemplate = stringRedisTemplate;
    }

    public void set(String key, Object value, Long time, TimeUnit unit) {
        // 将object任意java对象序列化为jason字符串
        stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(value),time,unit);
    }

        public void setWithLogicalExpire(String key, Object value, Long time, TimeUnit unit) {
        RedisData redisData = new RedisData();
        redisData.setData(value);
       // 设置了redisData的逻辑过期时间，交给自己
        redisData.setExpireTime(LocalDateTime.now().plusSeconds(unit.toSeconds(time)));

        // 写入redis,没有设置redis的过期时间
        stringRedisTemplate.opsForValue().set(key,JSONUtil.toJsonStr(redisData));
    }

    // 设置空缓存解决缓存穿透
    public <R,ID> R queryWithPassThrough(String keyPrefix, ID id, Class<R> type, Function<ID,R> dbFallback,
                                         Long time, TimeUnit unit) {
        // 1.从redis查商铺缓存
        String json = stringRedisTemplate.opsForValue().get(keyPrefix + id);
        // 2.判断该商铺在redis中的缓存是否存在
        if(StrUtil.isNotBlank(json)) {
            // 3.存在，直接返回信息
            return JSONUtil.toBean(json, type);
        }
        // 如果是空值
        if ("".equals(json) ) {
            // 返回错误信息
            return null;
        }
        // 4.不存在，根据id去数据库查，如果数据库没有，将空值写入redis并返回错误
        R r = dbFallback.apply(id);

        if(r == null) {
            stringRedisTemplate.opsForValue().set(keyPrefix + id,"",CACHE_NULL_TTL, TimeUnit.MINUTES);
            return null;
        }
        // 5.数据库存在，写入redis，并设置过期时间
        this.set(keyPrefix + id,r,time,unit);
        return r;
    }
    // 获取锁
    private boolean tryLock(String key) {
        Boolean flag = stringRedisTemplate.opsForValue().setIfAbsent(key, "1", 10, TimeUnit.SECONDS);
        return BooleanUtil.isTrue(flag);
    }
    // 删除锁
    private void unlock(String key) {
        stringRedisTemplate.delete(key);
    }

    // 逻辑过期解决缓存击穿
    public static final ExecutorService CACHE_REBUILD_EXECUTOR = Executors.newFixedThreadPool(10);
    public <R,ID> R queryWithLogicalExpire(String keyPrefix,ID id,Class<R> type,Function<ID,R> dbFallback
            ,Long time, TimeUnit unit) {
        // 1.从redis查商铺缓存
        String shopJson = stringRedisTemplate.opsForValue().get(keyPrefix + id);
        // 2.判断该商铺在redis中的缓存是否存在
        if(StrUtil.isBlank(shopJson)) {
            // 3.不存在，直接返回null
            return null;
        }
        RedisData redisData = JSONUtil.toBean(shopJson, RedisData.class);
        R r = JSONUtil.toBean((JSONObject) redisData.getData(), type);
        LocalDateTime expireTime = redisData.getExpireTime();
        // 判断是否过期
        if(expireTime.isAfter(LocalDateTime.now())) {
            return r;
        }
        // 过期重建缓存
        String lockKey = LOCK_SHOP_KEY + id;
        boolean isLock = tryLock(lockKey);
        if(isLock) {
            // todo 开启新线程
            CACHE_REBUILD_EXECUTOR.submit(()->{
                try {
                    // dbFallback查数据库 -> set写入缓存
                    this.setWithLogicalExpire(keyPrefix+id,dbFallback.apply(id),time,unit);
                } catch (Exception e) {
                    throw new RuntimeException(e);
                } finally {
                    unlock(lockKey);
                }
            });
        }
        return r;

    }
}

