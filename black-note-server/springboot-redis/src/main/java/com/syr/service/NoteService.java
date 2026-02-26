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
}