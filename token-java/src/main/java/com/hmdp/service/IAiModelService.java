package com.hmdp.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmdp.dto.Result;
import com.hmdp.entity.AiModel;

public interface IAiModelService extends IService<AiModel> {
    Result queryDetail(Long id);
    Result queryHot(String category, Integer current);
    Result search(String keyword, Integer current);
    Result updateModel(AiModel model);
}
