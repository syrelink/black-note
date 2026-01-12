package com.syr.service.Impl;

import cn.hutool.core.bean.BeanUtil;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.vo.SeckillVoucherVO;
import com.syr.vo.VoucherVO;
import com.syr.entity.SeckillVoucher;
import com.syr.entity.Shop;
import com.syr.entity.Voucher;
import com.syr.mapper.VoucherMapper;
import com.syr.service.ISeckillVoucherService;
import com.syr.service.IShopService;
import com.syr.service.IVoucherService;
import com.syr.utils.SystemConstants;
import jakarta.annotation.Resource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

import static com.syr.utils.RedisConstants.SECKILL_STOCK_KEY;

@Service
public class VoucherServiceImpl extends ServiceImpl<VoucherMapper, Voucher> implements IVoucherService {

    @Resource
    private ISeckillVoucherService seckillVoucherService;
    @Resource
    private StringRedisTemplate stringRedisTemplate;
    @Resource
    private IShopService shopService;

    @Override
    public void addSeckillVoucher(Voucher voucher) {
        save(voucher);

        SeckillVoucher seckillVoucher = new SeckillVoucher();
        seckillVoucher.setVoucherId(voucher.getId());
        seckillVoucher.setStock(voucher.getStock());
        seckillVoucher.setBeginTime(voucher.getBeginTime());
        seckillVoucher.setEndTime(voucher.getEndTime());

        seckillVoucherService.save(seckillVoucher);

        stringRedisTemplate.opsForValue().set(SECKILL_STOCK_KEY + voucher.getId(), voucher.getStock().toString());
    }

    @Override
    public List<VoucherVO> queryVoucherList(Integer current) {
        Page<Voucher> page = query()
                .eq("status", 1)
                .orderByDesc("create_time")
                .page(new Page<>(current, SystemConstants.MAX_PAGE_SIZE));

        List<Voucher> vouchers = page.getRecords();

        return vouchers.stream().map(voucher -> {
            VoucherVO vo = BeanUtil.copyProperties(voucher, VoucherVO.class);
            if (voucher.getShopId() != null) {
                Shop shop = shopService.queryById(voucher.getShopId());
                if (shop != null) {
                    vo.setShopName(shop.getName());
                }
            }
            return vo;
        }).collect(Collectors.toList());
    }

    @Override
    public List<SeckillVoucherVO> querySeckillVouchers() {
        LocalDateTime now = LocalDateTime.now();

        List<SeckillVoucher> seckillVouchers = seckillVoucherService.query()
                .le("begin_time", now)
                .ge("end_time", now)
                .gt("stock", 0)
                .list();

        if (seckillVouchers.isEmpty()) {
            return Collections.emptyList();
        }

        List<Long> voucherIds = seckillVouchers.stream()
                .map(SeckillVoucher::getVoucherId)
                .collect(Collectors.toList());

        List<Voucher> vouchers = listByIds(voucherIds);

        return vouchers.stream().map(voucher -> {
            SeckillVoucherVO vo = BeanUtil.copyProperties(voucher, SeckillVoucherVO.class);

            seckillVouchers.stream()
                    .filter(sv -> sv.getVoucherId().equals(voucher.getId()))
                    .findFirst()
                    .ifPresent(sv -> {
                        vo.setStock(sv.getStock());
                        vo.setBeginTime(sv.getBeginTime());
                        vo.setEndTime(sv.getEndTime());

                        LocalDateTime beginTime = sv.getBeginTime();
                        LocalDateTime endTime = sv.getEndTime();
                        LocalDateTime currentTime = LocalDateTime.now();

                        if (currentTime.isBefore(beginTime)) {
                            vo.setStatus("未开始");
                            vo.setCountdown(Duration.between(currentTime, beginTime).getSeconds());
                        } else if (currentTime.isAfter(endTime)) {
                            vo.setStatus("已结束");
                            vo.setCountdown(0L);
                        } else {
                            vo.setStatus("进行中");
                            vo.setCountdown(Duration.between(currentTime, endTime).getSeconds());
                        }
                    });

            if (voucher.getShopId() != null) {
                Shop shop = shopService.queryById(voucher.getShopId());
                if (shop != null) {
                    vo.setShopName(shop.getName());
                }
            }

            return vo;
        }).collect(Collectors.toList());
    }
}
