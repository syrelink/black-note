package com.syr.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.syr.dto.NotePublishDTO;
import com.syr.entity.Note;
import com.syr.vo.NoteVO;
import java.util.List;

public interface NoteService extends IService<Note> {
    void publish(NotePublishDTO dto);
    NoteVO getNoteById(Long id);
    void deleteNote(Long id);
    List<NoteVO> listByUser(Long userId);
    void like(Long noteId);
    Long getLikeCount(Long noteId);

    // ── 查询当前用户是否点赞了某笔记 ──
    // 新增接口：前端刷新后调用，恢复点赞状态
    Boolean isLiked(Long noteId);

    List<NoteVO> noteList(Integer page, Integer size);

}