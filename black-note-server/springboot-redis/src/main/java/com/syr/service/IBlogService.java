package com.syr.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.syr.dto.CommentDTO;
import com.syr.vo.CommentVO;
import com.syr.dto.ScrollResult;
import com.syr.dto.UserDTO;
import com.syr.entity.Blog;

import java.util.List;


public interface IBlogService extends IService<Blog> {

    /**
     * 根据ID查询博客详情
     */
    Blog queryBlogById(Long id);

    /**
     * 查询热门博客
     */
    List<Blog> queryHotBlog(Integer current);

    /**
     * 点赞/取消点赞
     */
    void likeBlog(Long id);

    /**
     * 查询点赞用户列表
     */
    List<UserDTO> queryBlogLikes(Long id);

    /**
     * 保存博文，返回新博文ID
     */
    Long saveBlog(Blog blog);

    /**
     * 关注Feed流，返回滚动分页结果
     */
    ScrollResult queryBlogOfFollow(Long maxTime, Integer offset);

    /**
     * 保存评论
     */
    void saveComment(Long id, CommentDTO commentDTO);

    /**
     * 分页查询评论列表
     */
    List<CommentVO> queryComments(Long id, Integer current);
}
