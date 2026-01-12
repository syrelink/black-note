package com.syr.service.Impl;

import com.syr.dto.Result;
import com.syr.mapper.ShopTypeMapper;

import com.syr.service.IShopTypeService;
import jakarta.annotation.Resource;

import com.syr.entity.ShopType;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import org.springframework.stereotype.Service;
import org.springframework.data.redis.core.StringRedisTemplate;

import cn.hutool.json.JSONUtil;
import java.util.List;


@Service
public class ShopTypeServiceImpl extends ServiceImpl<ShopTypeMapper, ShopType> implements IShopTypeService {


    @Resource
    private StringRedisTemplate stringRedisTemplate;

    public Result getShopTypeList() {

        String shopTypeListJson = stringRedisTemplate.opsForValue().get("shop-type-list");
        if(shopTypeListJson != null) {
            return Result.ok(JSONUtil.toList(shopTypeListJson, ShopType.class));
        }
        List<ShopType> shopTypeList = lambdaQuery().list();
        stringRedisTemplate.opsForValue().set("shop-type-list", JSONUtil.toJsonStr(shopTypeList));

        return Result.ok(shopTypeList); 
    }
}
