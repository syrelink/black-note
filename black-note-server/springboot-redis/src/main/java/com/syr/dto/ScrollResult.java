package com.syr.dto;

import lombok.Data;

import java.util.List;

// dto/ScrollResult.java
@Data
public class ScrollResult {
    private List<?> list;
    private Long minTime;
    private Integer offset;
}