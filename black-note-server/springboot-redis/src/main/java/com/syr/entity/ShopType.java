package com.syr.entity;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;
@Data
@TableName("tb_shop_type")
@Accessors(chain = true)

public class ShopType {
    private Long id;
    private String name;
    private String icon;
    private Long sort;
    private LocalDateTime createTime;
    private LocalDateTime updateTime;
}
