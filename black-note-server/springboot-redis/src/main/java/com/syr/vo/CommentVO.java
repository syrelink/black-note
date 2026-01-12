package com.syr.vo;
import lombok.Data;
import java.time.LocalDateTime;
import java.util.List;

@Data
public class CommentVO {
    private Long id;
    private Long userId;
    private String nickName;    // 评论者昵称
    private String icon;        // 评论者头像
    private String content;     // 评论内容
    private Integer liked;      // 点赞数
    private LocalDateTime createTime;
    // --- 核心字段 ---
    private Long rootId;           // 属于哪个根评论
    private String targetNickName; // 被回复的人（显示：A 回复 B）
    private List<CommentVO> replies; // 子评论列表

}