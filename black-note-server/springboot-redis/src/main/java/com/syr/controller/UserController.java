package com.syr.controller;

import cn.hutool.core.bean.BeanUtil;
import com.syr.dto.LoginFormDto;
import com.syr.dto.Result;
import com.syr.dto.UserDTO;
import com.syr.entity.User;
import com.syr.entity.UserInfo;
import com.syr.service.IUserInfoService;
import com.syr.service.IUserService;
import com.syr.utils.UserHolder;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.annotation.Resource;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;


@Tag(name = "用户管理", description = "处理用户登录、注册、信息查询等功能")
@Slf4j
@RestController
@RequestMapping("user")
public class UserController {

    @Resource
    private IUserService userService;
    @Resource
    private IUserInfoService userInfoService;

    @Operation(summary = "发送短信验证码", description = "向指定手机号发送短信验证码，用于登录或注册")
    @Parameter(name = "phone", description = "手机号码", required = true, example = "13800138000")
    @PostMapping("code")
    public Result sendCode(@RequestParam String phone) {
        userService.sendCode(phone);
        return Result.ok();
    }

    @Operation(summary = "用户登录/注册", description = "使用手机号和验证码进行登录，如果用户不存在则自动注册")
    @PostMapping("login")
    public Result login(@RequestBody LoginFormDto loginForm) {
        String token = userService.login(loginForm);
        return Result.ok(token);
    }

    @Operation(summary = "获取当前用户信息", description = "获取当前登录用户的详细信息")
    @GetMapping("me")
    public Result me() {
        UserDTO user = UserHolder.getUser();
        return Result.ok(user);
    }

    @Operation(summary = "根据ID查询用户信息", description = "根据用户ID查询用户的详细信息")
    @Parameter(name = "id", description = "用户ID", required = true, example = "1")
    @GetMapping("/{id}")
    public Result queryUserById(@PathVariable("id") Long id) {
        User user = userService.getById(id);
        if (user == null) {
            return Result.ok();
        }
        UserDTO userDTO = BeanUtil.copyProperties(user, UserDTO.class);
        return Result.ok(userDTO);
    }

    @Operation(summary = "查询用户详细信息", description = "查询用户的扩展信息，包括个人资料等")
    @Parameter(name = "userId", description = "用户ID", required = true, example = "1")
    @GetMapping("info/{userId}")
    public Result info(@PathVariable("userId") Long userId) {
        UserInfo info = userInfoService.getById(userId);
        if (info == null) {
            return Result.ok();
        }
        info.setCreateTime(null);
        info.setUpdateTime(null);
        return Result.ok(info);
    }
}
