package com.syr.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.syr.entity.User;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface UserMapper extends BaseMapper<User> {

}
