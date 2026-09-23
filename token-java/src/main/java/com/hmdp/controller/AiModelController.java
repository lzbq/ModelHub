package com.hmdp.controller;

import com.hmdp.dto.Result;
import com.hmdp.service.IAiModelService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import jakarta.annotation.Resource;

@RestController
@RequestMapping("/ai-model")
public class AiModelController {
    /*
    * 查询模型详情、热门榜单和关键字搜索。详情内部自动区分普通模型和热门模型缓存策略。
    * */
    @Resource
    private IAiModelService aiModelService;

    @GetMapping("/{id}")
    public Result detail(@PathVariable Long id) {
        return aiModelService.queryDetail(id);
    }

    @GetMapping("/hot")
    public Result hot(@RequestParam(required = false) String category,
                      @RequestParam(defaultValue = "1") Integer current) {
        return aiModelService.queryHot(category, current);
    }

    @GetMapping("/search")
    public Result search(@RequestParam String keyword,
                         @RequestParam(defaultValue = "1") Integer current) {
        return aiModelService.search(keyword, current);
    }
}
