// dto/VoucherVO.java
package com.syr.vo;

import lombok.Data;
import java.time.LocalDateTime;

@Data
public class VoucherVO {
    private Long id;
    private Long shopId;
    private String shopName;    // 店铺名称
    private String title;       // 优惠券标题
    private String subTitle;    // 副标题
    private String rules;       // 使用规则
    private Long payValue;      // 支付金额
    private Long actualValue;   // 抵扣金额
    private Integer type;       // 类型
    private LocalDateTime createTime;
}