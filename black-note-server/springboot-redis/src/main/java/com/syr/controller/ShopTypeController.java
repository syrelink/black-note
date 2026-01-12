package com.syr.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import com.syr.dto.Result;
import com.syr.service.IShopTypeService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.annotation.Resource;

@Tag(name = "店铺类型管理", description = "处理店铺类型列表的查询功能")
@RestController
@RequestMapping("shop-type")
public class ShopTypeController {

    @Resource
    private IShopTypeService shopTypeService;

    @Operation(summary = "获取店铺类型列表", description = "获取所有可用的店铺类型列表")
    @GetMapping("list")
    public Result getShopTypeList() {
        return Result.ok(shopTypeService.getShopTypeList());
    }
}
