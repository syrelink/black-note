package com.syr.service.Impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.entity.SeckillVoucher;
import com.syr.mapper.SeckillVoucheMapper;
import com.syr.service.ISeckillVoucherService;
import org.springframework.stereotype.Service;

@Service
public class SeckillVoucherServiceImpl extends ServiceImpl<SeckillVoucheMapper,SeckillVoucher> implements ISeckillVoucherService {
}
