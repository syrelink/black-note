package com.syr.service.Impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.entity.Shop;
import com.syr.exception.BusinessException;
import com.syr.mapper.ShopMapper;
import com.syr.service.IShopService;
import com.syr.utils.CacheClient;
import jakarta.annotation.Resource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Collections;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static com.syr.utils.RedisConstants.*;

@Service
public class ShopServiceImpl extends ServiceImpl<ShopMapper, Shop> implements IShopService {

    @Resource
    private StringRedisTemplate stringRedisTemplate;

    @Resource
    private CacheClient cacheClient;

    @Override
    public Shop queryById(Long id) {
        Shop shop = cacheClient.queryWithLogicalExpire(CACHE_SHOP_KEY, id,
                Shop.class, this::getById, CACHE_SHOP_TTL, TimeUnit.MINUTES);

        if (shop == null) {
            throw new BusinessException("店铺不存在！");
        }
        return shop;
    }

    @Override
    @Transactional
    public void updateShop(Shop shop) {
        if (shop.getId() == null) {
            throw new IllegalArgumentException("店铺ID不能为空");
        }
        updateById(shop);
        stringRedisTemplate.delete(CACHE_SHOP_KEY + shop.getId());
    }

    @Override
    public List<Shop> queryShopList(Long typeId, Integer current) {
        // TODO: 实现分页查询逻辑
        return Collections.emptyList();
    }
}
