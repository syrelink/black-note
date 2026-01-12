package com.syr.service.Impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.dto.CommentDTO;
import com.syr.vo.CommentVO;
import com.syr.dto.ScrollResult;
import com.syr.dto.UserDTO;
import com.syr.entity.Blog;
import com.syr.entity.BlogComments;
import com.syr.entity.Follow;
import com.syr.entity.User;
import com.syr.exception.BusinessException;
import com.syr.mapper.BlogMappper;
import com.syr.service.IBlogCommentsService;
import com.syr.service.IBlogService;
import com.syr.service.IFollowService;
import com.syr.service.IUserService;
import com.syr.utils.SystemConstants;
import com.syr.utils.UserHolder;
import jakarta.annotation.Resource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.stream.Collectors;

import static com.syr.utils.RedisConstants.BLOG_LIKED_KEY;
import static com.syr.utils.RedisConstants.FEED_KEY;

@Service
public class BlogServiceImpl extends ServiceImpl<BlogMappper, Blog> implements IBlogService {

    @Resource
    private IUserService userService;
    @Resource
    private IFollowService followService;
    @Resource
    private StringRedisTemplate stringRedisTemplate;
    @Resource
    private IBlogCommentsService blogCommentsService;

    @Override
    public Blog queryBlogById(Long id) {
        Blog blog = getById(id);
        if (blog == null) {
            throw new BusinessException("笔记不存在");
        }
        queryBlogUser(blog);
        isBlogLiked(blog);
        return blog;
    }

    private void isBlogLiked(Blog blog) {
        UserDTO user = UserHolder.getUser();
        if (user == null) return;

        Long userId = user.getId();
        String key = "blog:liked:" + blog.getId();
        Double score = stringRedisTemplate.opsForZSet().score(key, userId.toString());
        blog.setIsLike(score != null);
    }

    @Override
    public List<Blog> queryHotBlog(Integer current) {
        Page<Blog> page = query()
                .orderByDesc("liked")
                .page(new Page<>(current, SystemConstants.MAX_PAGE_SIZE));
        List<Blog> records = page.getRecords();
        records.forEach(blog -> {
            this.queryBlogUser(blog);
            this.isBlogLiked(blog);
        });
        return records;
    }

    @Override
    public void likeBlog(Long id) {
        Long userId = UserHolder.getUser().getId();
        String key = "blog:liked:" + id;
        Double score = stringRedisTemplate.opsForZSet().score(key, userId.toString());

        if (score == null) {
            boolean isSuccess = update().setSql("liked = liked + 1").eq("id", id).update();
            if (isSuccess) {
                stringRedisTemplate.opsForZSet().add(key, userId.toString(), System.currentTimeMillis());
            }
        } else {
            boolean isSuccess = update().setSql("liked = liked - 1").eq("id", id).update();
            if (isSuccess) {
                stringRedisTemplate.opsForZSet().remove(key, userId.toString());
            }
        }
    }

    @Override
    public List<UserDTO> queryBlogLikes(Long id) {
        String key = BLOG_LIKED_KEY + id;
        Set<String> top5 = stringRedisTemplate.opsForZSet().range(key, 0, 4);

        if (top5 == null || top5.isEmpty()) {
            return Collections.emptyList();
        }

        List<Long> ids = top5.stream().map(Long::valueOf).collect(Collectors.toList());
        String idStr = StrUtil.join(",", ids);

        return userService.query().in("id", ids)
                .last("ORDER BY FIELD(id," + idStr + ")").list()
                .stream()
                .map(user -> BeanUtil.copyProperties(user, UserDTO.class))
                .collect(Collectors.toList());
    }

    @Override
    public Long saveBlog(Blog blog) {
        UserDTO user = UserHolder.getUser();
        blog.setUserId(user.getId());

        boolean isSuccess = save(blog);
        if (!isSuccess) {
            throw new BusinessException("新增笔记失败！");
        }

        // 推送给粉丝
        List<Follow> follows = followService.query().eq("follow_user_id", user.getId()).list();
        for (Follow follow : follows) {
            Long userId = follow.getUserId();
            String key = "feed:" + userId;
            stringRedisTemplate.opsForZSet().add(key, blog.getId().toString(), System.currentTimeMillis());
        }

        return blog.getId();
    }

    @Override
    public ScrollResult queryBlogOfFollow(Long max, Integer offset) {
        Long userId = UserHolder.getUser().getId();
        String key = FEED_KEY + userId;
        Set<ZSetOperations.TypedTuple<String>> typedTuples = stringRedisTemplate.opsForZSet()
                .reverseRangeByScoreWithScores(key, 0, max == null ? System.currentTimeMillis() : max, offset, 3);

        if (typedTuples == null || typedTuples.isEmpty()) {
            return null;
        }

        List<Long> ids = new ArrayList<>(typedTuples.size());
        long minTime = 0;
        int os = 1;
        for (ZSetOperations.TypedTuple<String> tuple : typedTuples) {
            ids.add(Long.valueOf(tuple.getValue()));
            long time = tuple.getScore().longValue();
            if (time == minTime) {
                os++;
            } else {
                minTime = time;
                os = 1;
            }
        }

        String idStr = StrUtil.join(",", ids);
        List<Blog> blogs = query().in("id", ids).last("ORDER BY FIELD(id," + idStr + ")").list();

        for (Blog blog : blogs) {
            queryBlogUser(blog);
            isBlogLiked(blog);
        }

        ScrollResult result = new ScrollResult();
        result.setList(blogs);
        result.setOffset(os);
        result.setMinTime(minTime);
        return result;
    }

    @Override
    public void saveComment(Long blogId, CommentDTO dto) {
        BlogComments comment = new BlogComments();
        comment.setBlogId(blogId);
        comment.setUserId(UserHolder.getUser().getId());
        comment.setContent(dto.getContent());

        // 树形核心逻辑：
        Long pId = dto.getParentId();
        if (pId == null || pId == 0) {
            // 场景：一级评论
            comment.setParentId(0L);
            comment.setRootId(0L);
            comment.setAnswerId(0L);
        } else {
            // 场景：回复别人
            BlogComments parent = blogCommentsService.getById(pId);
            if (parent == null) throw new BusinessException("父评论不存在");

            comment.setParentId(pId);
            comment.setAnswerId(parent.getUserId()); // 被回复的人就是父评论的作者

            // 关键点：如果父评论没有rootId，说明父评论就是根；否则，跟从父评论的根
            comment.setRootId(parent.getRootId() == 0 ? parent.getId() : parent.getRootId());
        }

        blogCommentsService.save(comment);
    }

    @Override
    public List<CommentVO> queryComments(Long blogId, Integer current) {
        // 1. 分页查询一级评论 (root_id = 0)
        Page<BlogComments> page = blogCommentsService.query()
                .eq("blog_id", blogId)
                .eq("root_id", 0)
                .orderByDesc("create_time")
                .page(new Page<>(current, SystemConstants.MAX_PAGE_SIZE));

        List<BlogComments> roots = page.getRecords();
        if (roots.isEmpty()) {
            return Collections.emptyList();
        }

        // 2. 批量查出这些一级评论下“所有”的二级回复
        List<Long> rootIds = roots.stream().map(BlogComments::getId).collect(Collectors.toList());
        List<BlogComments> children = blogCommentsService.query()
                .in("root_id", rootIds)
                .orderByAsc("create_time")
                .list();

        // 3. 收集所有相关的用户 ID（评论者 + 被回复者）进行批量查询
        Set<Long> uIds = new HashSet<>();
        roots.forEach(r -> uIds.add(r.getUserId()));
        children.forEach(c -> {
            uIds.add(c.getUserId());
            uIds.add(c.getAnswerId());
        });
        uIds.remove(0L); // 移除默认值 0

        // 批量查出用户信息存入 Map (UserID -> User)
        Map<Long, User> userMap = userService.listByIds(uIds).stream()
                .collect(Collectors.toMap(User::getId, u -> u));

        // 4. 将所有子评论转为 VO，并按 root_id 分组
        Map<Long, List<CommentVO>> repliesMap = children.stream().map(c -> {
            CommentVO vo = convertToVO(c, userMap);
            // 如果是回复某人，补充被回复者的名字
            User targetUser = userMap.get(c.getAnswerId());
            if (targetUser != null) {
                vo.setTargetNickName(targetUser.getNickName());
            }
            return vo;
        }).collect(Collectors.groupingBy(CommentVO::getRootId));

        // 5. 将回复列表塞进对应的一级评论 VO 中
        return roots.stream().map(r -> {
            CommentVO vo = convertToVO(r, userMap);
            vo.setReplies(repliesMap.get(r.getId())); // 关键：父子合并
            return vo;
        }).collect(Collectors.toList());
    }

    // 辅助转换方法
    private CommentVO convertToVO(BlogComments c, Map<Long, User> userMap) {
        CommentVO vo = BeanUtil.copyProperties(c, CommentVO.class);
        User user = userMap.get(c.getUserId());
        if (user != null) {
            vo.setNickName(user.getNickName());
            vo.setIcon(user.getIcon());
        }
        return vo;
    }

    private void queryBlogUser(Blog blog) {
        Long userId = blog.getUserId();
        User user = userService.getById(userId);
        blog.setName(user.getNickName());
        blog.setIcon(user.getIcon());
    }
}
