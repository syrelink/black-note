package com.syr.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.syr.entity.NoteLike;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface NoteLikeMapper extends BaseMapper<NoteLike> {

    @Delete("DELETE FROM note_like WHERE user_id = #{userId} AND note_id = #{noteId}")
    void deleteByUserIdAndNoteId(Long userId, Long noteId);
}