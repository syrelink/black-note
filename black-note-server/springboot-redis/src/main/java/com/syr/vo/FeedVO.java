package com.syr.vo;


import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import java.util.Collections;
import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class FeedVO {

    // 本次返回的笔记列表
    private List<NoteVO> list;

    // 下次请求的游标（最后一条的时间戳），前端带上这个值请求下一页
    private Long nextTimestamp;

    // 是否还有更多数据
    private Boolean hasMore;

    // 空结果工厂方法
    public static FeedVO empty() {
        return FeedVO.builder()
                .list(Collections.emptyList())
                .nextTimestamp(0L)
                .hasMore(false)
                .build();
    }
}