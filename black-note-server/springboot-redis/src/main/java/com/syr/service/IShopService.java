package com.syr.service;

import com.syr.entity.Shop;

import java.util.List;


public interface IShopService {

   // 根据 ID 查询，直接返回 Shop 实体
   Shop queryById(Long id);

   // 更新操作，成功与否通过异常或 Boolean 控制，这里建议 void 或 boolean
   void updateShop(Shop shop);

   // 分页查询列表，返回 List 集合
   List<Shop> queryShopList(Long typeId, Integer current);


}