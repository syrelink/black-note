package com.syr.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import java.time.LocalDateTime;
import java.io.Serializable;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

/**
 * 评论实体类
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("tb_blog_comments")
public class BlogComments implements Serializable {

    private static final long serialVersionUID = 1L;

    /**
     * 主键
     */
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /**
     * 用户id
     */
    private Long userId;

    /**
     * 探店id
     */
    private Long blogId;

    /**
     * 【新增】根评论id
     * 若为0表示这是一级评论；若不为0，则指向该回复所属的最顶层一级评论ID
     */
    private Long rootId;

    /**
     * 父评论id
     * 直接回复的那条评论ID，如果是一级评论，则值为0
     */
    private Long parentId;

    /**
     * 回复的目标用户id
     * 注意：这里建议对应数据库的 answer_id，表示你回复的是“谁”
     */
    private Long answerId;

    /**
     * 回复的内容
     */
    private String content;

    /**
     * 点赞数
     */
    private Integer liked;

    /**
     * 状态
     * 修改为 Integer，因为数据库定义了 0:正常, 1:被举报, 2:禁止查看
     * Boolean 只能表达 0 和 1，无法表达 2
     */
    private Integer status;

    /**
     * 创建时间
     */
    private LocalDateTime createTime;

    /**
     * 更新时间
     */
    private LocalDateTime updateTime;
}