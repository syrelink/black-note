package com.syr.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.syr.entity.VoucherOrder;

public interface IVoucherOrderService extends IService<VoucherOrder> {

    /**
     * 秒杀优惠券
     * @return 订单ID
     */
    Long seckillVoucher(Long voucherId);

    /**
     * 创建优惠券订单
     * @return 订单ID
     */
    Long createVoucherOrder(Long voucherId);
}
