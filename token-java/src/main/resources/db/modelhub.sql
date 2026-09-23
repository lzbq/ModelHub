-- ModelHub 独立初始化脚本（MySQL 8.x）。
CREATE DATABASE IF NOT EXISTS `modelhub`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE `modelhub`;

CREATE TABLE IF NOT EXISTS `tb_user` (
  `id` bigint UNSIGNED NOT NULL AUTO_INCREMENT,
  `phone` varchar(11) NOT NULL COMMENT '手机号',
  `password` varchar(128) DEFAULT NULL COMMENT '预留的加密密码',
  `nick_name` varchar(32) NOT NULL,
  `icon` varchar(255) DEFAULT '',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_phone` (`phone`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='ModelHub 用户';

CREATE TABLE IF NOT EXISTS `tb_ai_model` (
  `id` bigint UNSIGNED NOT NULL AUTO_INCREMENT,
  `provider` varchar(64) NOT NULL COMMENT '模型厂商',
  `name` varchar(128) NOT NULL COMMENT '模型名称',
  `category` varchar(32) NOT NULL COMMENT 'chat/reasoning/embedding/image',
  `description` varchar(1024) DEFAULT NULL,
  `context_window` int UNSIGNED NOT NULL DEFAULT 0,
  `input_price` bigint UNSIGNED NOT NULL DEFAULT 0 COMMENT '分/百万输入 Token',
  `output_price` bigint UNSIGNED NOT NULL DEFAULT 0 COMMENT '分/百万输出 Token',
  `status` tinyint UNSIGNED NOT NULL DEFAULT 1,
  `hot_score` bigint UNSIGNED NOT NULL DEFAULT 0 COMMENT '动态热度分，范围 0~10000',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_category_hot` (`category`, `hot_score`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='大模型商品目录';

CREATE TABLE IF NOT EXISTS `tb_token_package` (
  `id` bigint UNSIGNED NOT NULL AUTO_INCREMENT,
  `model_id` bigint UNSIGNED NOT NULL,
  `title` varchar(128) NOT NULL,
  `sub_title` varchar(256) DEFAULT NULL,
  `rules` varchar(1024) DEFAULT NULL,
  `token_quota` bigint UNSIGNED NOT NULL,
  `pay_value` bigint UNSIGNED NOT NULL COMMENT '价格，单位分',
  `valid_days` int UNSIGNED NOT NULL DEFAULT 30,
  `type` tinyint UNSIGNED NOT NULL DEFAULT 0 COMMENT '0 普通套餐，1 限时抢购',
  `status` tinyint UNSIGNED NOT NULL DEFAULT 1,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_model_status` (`model_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Token 额度套餐';

CREATE TABLE IF NOT EXISTS `tb_seckill_token_package` (
  `package_id` bigint UNSIGNED NOT NULL,
  `stock` int UNSIGNED NOT NULL,
  `begin_time` timestamp NOT NULL,
  `end_time` timestamp NOT NULL,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`package_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='限时 Token 套餐库存';

CREATE TABLE IF NOT EXISTS `tb_token_order` (
  `id` bigint NOT NULL,
  `user_id` bigint UNSIGNED NOT NULL,
  `package_id` bigint UNSIGNED NOT NULL,
  `quota_amount` bigint UNSIGNED NOT NULL,
  `pay_type` tinyint UNSIGNED DEFAULT NULL,
  `status` tinyint UNSIGNED NOT NULL DEFAULT 1 COMMENT '1 未支付，2 已支付并发放，4 已取消',
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `pay_time` timestamp NULL DEFAULT NULL,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_package` (`user_id`, `package_id`),
  KEY `idx_status_create` (`status`, `create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Token 套餐订单';

CREATE TABLE IF NOT EXISTS `tb_token_account` (
  `id` bigint UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` bigint UNSIGNED NOT NULL,
  `model_id` bigint UNSIGNED NOT NULL,
  `total_quota` bigint UNSIGNED NOT NULL DEFAULT 0,
  `used_quota` bigint UNSIGNED NOT NULL DEFAULT 0,
  `reserved_quota` bigint UNSIGNED NOT NULL DEFAULT 0 COMMENT '网关请求预留额度',
  `expire_time` timestamp NULL DEFAULT NULL,
  `version` int UNSIGNED NOT NULL DEFAULT 0,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_model` (`user_id`, `model_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户模型 Token 额度账户';

CREATE TABLE IF NOT EXISTS `tb_token_quota_record` (
  `id` bigint UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` bigint UNSIGNED NOT NULL,
  `model_id` bigint UNSIGNED NOT NULL,
  `order_id` bigint NOT NULL,
  `change_amount` bigint NOT NULL,
  `change_type` varchar(32) NOT NULL,
  `balance_after` bigint NOT NULL,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_grant` (`order_id`),
  KEY `idx_user_model_time` (`user_id`, `model_id`, `create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Token 额度审计流水';

INSERT INTO `tb_ai_model`
(`id`, `provider`, `name`, `category`, `description`, `context_window`, `input_price`, `output_price`, `status`, `hot_score`)
VALUES
(1, 'OpenAI', 'GPT 通用模型', 'chat', '适合通用问答、内容生成和结构化提取', 128000, 100, 400, 1, 9800),
(2, 'Anthropic', 'Claude 长文本模型', 'chat', '适合长文档理解、代码分析与写作', 200000, 300, 1500, 1, 9200),
(3, 'DeepSeek', 'DeepSeek 推理模型', 'reasoning', '适合数学、代码和复杂推理任务', 64000, 50, 200, 1, 9900),
(4, 'BAAI', 'BGE 中文向量模型', 'embedding', '适合中文知识库检索和语义召回', 8192, 10, 0, 1, 7600)
ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`);

INSERT INTO `tb_token_package`
(`id`, `model_id`, `title`, `sub_title`, `rules`, `token_quota`, `pay_value`, `valid_days`, `type`, `status`)
VALUES
(1, 3, '推理模型限时体验包', '100 万 Token，限时抢购', '每位用户限购一份；支付后到账；有效期 30 天', 1000000, 990, 30, 1, 1),
(2, 1, '通用开发包', '500 万 Token', '支付后到账；有效期 90 天', 5000000, 4990, 90, 0, 1),
(3, 4, '中文向量检索包', '1000 万 Token', '仅适用于 Embedding 接口；有效期 180 天', 10000000, 1990, 180, 0, 1)
ON DUPLICATE KEY UPDATE
  `title` = VALUES(`title`),
  `token_quota` = VALUES(`token_quota`);

INSERT INTO `tb_seckill_token_package` (`package_id`, `stock`, `begin_time`, `end_time`)
VALUES (1, 10000, '2026-01-01 00:00:00', '2030-12-31 23:59:59')
ON DUPLICATE KEY UPDATE
  `stock` = VALUES(`stock`),
  `begin_time` = VALUES(`begin_time`),
  `end_time` = VALUES(`end_time`);

-- Redis 初始化命令见项目根目录 ModelHub_运行步骤.md。
