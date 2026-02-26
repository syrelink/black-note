package com.syr.controller;


import com.syr.dto.Result;
import com.syr.dto.NotePublishDTO;
import com.syr.service.NoteService;
import com.syr.vo.NoteVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import jakarta.validation.Valid;
import java.util.List;

@RestController
@RequestMapping("/note")
@RequiredArgsConstructor
public class NoteController {

    private final NoteService noteService;

    @PostMapping("/publish")
    public Result<Void> publish(@RequestBody @Valid NotePublishDTO dto) {
        noteService.publish(dto);
        return Result.success(null);
    }

    @GetMapping("/{id}")
    public Result<NoteVO> getNoteById(@PathVariable Long id) {
        return Result.success(noteService.getNoteById(id));
    }

    @DeleteMapping("/{id}")
    public Result<Void> deleteNote(@PathVariable Long id) {
        noteService.deleteNote(id);
        return Result.success(null);
    }

    @GetMapping("/list/{userId}")
    public Result<List<NoteVO>> listByUser(@PathVariable Long userId) {
        return Result.success(noteService.listByUser(userId));
    }

    @PostMapping("/like/{noteId}")
    public Result<Void> like(@PathVariable Long noteId) {
        noteService.like(noteId);
        return Result.success(null);
    }

    @GetMapping("/like/count/{noteId}")
    public Result<Long> getLikeCount(@PathVariable Long noteId) {
        return Result.success(noteService.getLikeCount(noteId));
    }
}