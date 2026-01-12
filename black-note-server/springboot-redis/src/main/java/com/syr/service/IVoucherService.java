package com.syr.service;

import com.syr.vo.SeckillVoucherVO;
import com.syr.vo.VoucherVO;
import com.syr.entity.Voucher;

import java.util.List;

public interface IVoucherService {

    /**
     * 新增秒杀优惠券
     */
    void addSeckillVoucher(Voucher voucher);

    /**
     * 查询优惠券列表
     */
    List<VoucherVO> queryVoucherList(Integer current);

    /**
     * 查询秒杀优惠券列表
     */
    List<SeckillVoucherVO> querySeckillVouchers();
}
