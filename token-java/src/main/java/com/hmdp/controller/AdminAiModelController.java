package com.hmdp.controller;

import com.hmdp.dto.Result;
import com.hmdp.entity.AiModel;
import com.hmdp.service.IAiModelService;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 模型运营接口。该路径不在公开接口白名单中，需要登录 token。 */
@RestController
@RequestMapping("/admin/ai-model")
public class AdminAiModelController {
    /*
    * 更新模型名称、分类、价格、状态或热度；触发事务提交后的 Redis/Caffeine 失效和 MQ 广播。
    * */

    @Resource
    private IAiModelService aiModelService;

    @PutMapping
    public Result update(@RequestBody AiModel model) {
        return aiModelService.updateModel(model);
    }
}
