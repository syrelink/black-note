package com.syr.service.Impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.syr.entity.BlogComments;
import com.syr.mapper.BlogCommentsMapper;
import com.syr.service.IBlogCommentsService;
import org.springframework.stereotype.Service;

@Service
public class BlogCommentsServiceImpl extends ServiceImpl<BlogCommentsMapper,BlogComments>
        implements IBlogCommentsService {


}
