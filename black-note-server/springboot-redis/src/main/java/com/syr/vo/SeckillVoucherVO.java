// dto/SeckillVoucherVO.java
package com.syr.vo;

import lombok.Data;
import java.time.LocalDateTime;

@Data
public class SeckillVoucherVO {
    private Long id;
    private Long shopId;
    private String shopName;        // 店铺名称
    private String title;           // 标题
    private String subTitle;        // 副标题
    private Long payValue;          // 支付金额
    private Long actualValue;       // 抵扣金额

    // 秒杀信息
    private Integer stock;          // 库存
    private LocalDateTime beginTime; // 开始时间
    private LocalDateTime endTime;   // 结束时间
    private String status;          // 状态：未开始、进行中、已结束
    private Long countdown;         // 倒计时（秒）
}