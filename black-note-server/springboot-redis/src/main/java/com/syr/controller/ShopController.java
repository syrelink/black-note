package com.syr.controller;

import com.syr.dto.Result;
import com.syr.vo.SeckillVoucherVO;
import com.syr.vo.VoucherVO;
import com.syr.entity.Shop;
import com.syr.service.IShopService;
import com.syr.service.IVoucherService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.*;

import java.util.List;


@Tag(name = "店铺管理", description = "处理店铺信息的查询和更新功能")
@RestController
@RequestMapping("shop")
public class ShopController {

    @Resource
    private IVoucherService voucherService;
    @Resource
    private IShopService shopService;

    @GetMapping("/list")
    @Operation(summary = "查询店铺列表")
    public Result queryShopList(
            @RequestParam(required = false) Long typeId,
            @RequestParam(defaultValue = "1") Integer current
    ) {
        List<Shop> shopList = shopService.queryShopList(typeId, current);
        return Result.ok(shopList);
    }

    @GetMapping("/voucher/list")
    @Operation(summary = "查询优惠券列表")
    public Result queryVoucherList(
            @RequestParam(defaultValue = "1") Integer current
    ) {
        List<VoucherVO> vouchers = voucherService.queryVoucherList(current);
        return Result.ok(vouchers);
    }

    @GetMapping("/seckill/list")
    @Operation(summary = "查询秒杀优惠券列表")
    public Result querySeckillVouchers() {
        List<SeckillVoucherVO> vouchers = voucherService.querySeckillVouchers();
        return Result.ok(vouchers);
    }

    @Operation(summary = "根据ID查询店铺信息", description = "根据店铺ID查询店铺的详细信息")
    @Parameter(name = "id", description = "店铺ID", required = true, example = "1")
    @GetMapping("/{id}")
    public Result queryShopById(@PathVariable Long id) {
        Shop shop = shopService.queryById(id);
        return Result.ok(shop);
    }

    @Operation(summary = "更新店铺信息", description = "更新店铺的详细信息")
    @PostMapping("/update")
    public Result updateShop(@RequestBody Shop shop) {
        shopService.updateShop(shop);
        return Result.ok();
    }
}
