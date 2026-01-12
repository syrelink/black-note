package com.syr.controller;

import com.syr.dto.Result;
import com.syr.service.IVoucherOrderService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "优惠券订单管理", description = "处理优惠券订单的秒杀下单功能")
@RestController
@RequestMapping("/voucher-order")
public class VoucherOrderController {

    @Resource
    private IVoucherOrderService voucherOrderService;

    @Operation(summary = "优惠券秒杀下单", description = "参与优惠券秒杀活动，创建优惠券订单")
    @Parameter(name = "voucherId", description = "优惠券ID", required = true, example = "1")
    @PostMapping("seckill/{voucherId}")
    public Result seckillVoucher(@PathVariable("voucherId") Long voucherId) {
        Long orderId = voucherOrderService.seckillVoucher(voucherId);
        return Result.ok(orderId);
    }
}
