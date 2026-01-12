package com.syr.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.syr.dto.CommentDTO;
import com.syr.vo.CommentVO;
import com.syr.dto.Result;
import com.syr.dto.ScrollResult;
import com.syr.dto.UserDTO;
import com.syr.entity.Blog;
import com.syr.service.IBlogService;
import com.syr.utils.SystemConstants;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.Parameters;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.*;

import java.util.List;


@Tag(name = "博客管理", description = "处理博文的发布、点赞、查询及排行榜，以及评论的发布查询")
@RestController
@RequestMapping("blog")
public class BlogController {

    @Resource
    private IBlogService blogService;

    @GetMapping("/of/follow")
    @Operation(summary = "查询关注用户的笔记", description = "滚动分页查询关注用户发布的笔记")
    public Result queryBlogOfFollow(
            @RequestParam(value = "lastId", required = false) Long maxTime,
            @RequestParam(value = "offset", defaultValue = "0") Integer offset
    ) {
        ScrollResult scrollResult = blogService.queryBlogOfFollow(maxTime, offset);
        return Result.ok(scrollResult);
    }

    @PostMapping("/{id}/comment")
    @Operation(summary = "发表评论")
    public Result saveComment(
            @PathVariable("id") Long blogId, // 这里的 id 对应路径里的笔记ID
            @RequestBody CommentDTO commentDTO
    ) {
        // 将笔记ID和DTO一起传给 Service
        blogService.saveComment(blogId, commentDTO);
        return Result.ok();
    }

    @GetMapping("/{id}/comments")
    @Operation(summary = "查询评论列表")
    public Result queryComments(
            @PathVariable Long id,
            @RequestParam(defaultValue = "1") Integer current
    ) {
        List<CommentVO> comments = blogService.queryComments(id, current);
        return Result.ok(comments);
    }

    @Operation(summary = "发布博文", description = "用户发布新的博文内容")
    @PostMapping
    public Result saveBlog(@RequestBody Blog blog) {
        Long blogId = blogService.saveBlog(blog);
        return Result.ok(blogId);
    }

    @Operation(summary = "查询博文点赞用户列表", description = "获取对指定博文点赞的所有用户信息")
    @Parameter(name = "id", description = "博文ID", required = true, example = "1")
    @GetMapping("/likes/{id}")
    public Result queryBlogLikes(@PathVariable("id") Long id) {
        List<UserDTO> users = blogService.queryBlogLikes(id);
        return Result.ok(users);
    }

    @Operation(summary = "点赞/取消点赞博文", description = "对指定博文进行点赞操作，如果已点赞则取消点赞")
    @Parameter(name = "id", description = "博文ID", required = true, example = "1")
    @PutMapping("/like/{id}")
    public Result likeBlog(@PathVariable("id") Long id) {
        blogService.likeBlog(id);
        return Result.ok();
    }

    @Operation(summary = "查询热门博文", description = "分页查询热门博文列表，按热度排序")
    @Parameter(name = "current", description = "当前页码", required = false, example = "1")
    @GetMapping("/hot")
    public Result queryHotBlog(@RequestParam(value = "current", defaultValue = "1") Integer current) {
        List<Blog> blogs = blogService.queryHotBlog(current);
        return Result.ok(blogs);
    }

    @Operation(summary = "根据ID查询博文详情", description = "根据博文ID查询完整的博文信息，包括作者信息等")
    @Parameter(name = "id", description = "博文ID", required = true, example = "1")
    @GetMapping("/{id}")
    public Result queryBlogById(@PathVariable("id") Long id) {
        Blog blog = blogService.queryBlogById(id);
        return Result.ok(blog);
    }

    @Operation(summary = "查询用户的博文列表", description = "分页查询指定用户发布的所有博文")
    @Parameters({
        @Parameter(name = "current", description = "当前页码", required = false, example = "1"),
        @Parameter(name = "id", description = "用户ID", required = true, example = "1")
    })
    @GetMapping("/of/user")
    public Result queryBlogByUser(
            @RequestParam(value = "current", defaultValue = "1") Integer current,
            @RequestParam("id") Long id
    ) {
        Page<Blog> page = blogService.query()
                .eq("user_id", id)
                .page(new Page<>(current, SystemConstants.MAX_PAGE_SIZE));
        List<Blog> records = page.getRecords();
        return Result.ok(records);
    }
}
