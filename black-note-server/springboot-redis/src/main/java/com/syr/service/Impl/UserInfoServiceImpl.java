package com.syr.service.Impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;

import com.syr.entity.UserInfo;
import com.syr.mapper.UserInfoMapper;
import com.syr.service.IUserInfoService;
import org.springframework.stereotype.Service;

@Service
public class UserInfoServiceImpl extends ServiceImpl<UserInfoMapper, UserInfo> implements IUserInfoService {
}
