package com.syr.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.syr.entity.Note;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface NoteMapper extends BaseMapper<Note> {
}