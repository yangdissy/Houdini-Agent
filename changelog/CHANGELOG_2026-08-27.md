# Changelog — 2026-08-27

## Manual 逻辑批次与验证屏障

- Streaming executor 仅合并连续 readonly 段，并保留所有 Houdini 调用相对顺序。
- registry 增加 execution barrier 语义；mutation、持久 Update Mode、临时验证成功后立即失效查询缓存。
- 查询 cache hit 使用深拷贝并保留 metadata，避免消费者修改污染缓存。
- 几何 wrapper 保留字符串结果并新增结构化 `data`、`health`、`freshness`。
- temporary Auto geometry validation 只 cook target，报告 cook/read/restore 状态，恢复失败不再宣称成功。
- `check_errors` 要求 `node_path`；Manual 下执行 scoped temporary Auto target validation 并恢复，Volume/VDB 安全跳过返回 unknown。
- `set_update_mode` 返回 requested/effective/mode_kind/persistent；Confirm Mode 下持久变更需要确认。
- 模型结果压缩保留 health/freshness/validation/restore/recovery 信号。
- 核心与 extra prompts、tool schema、i18n 统一为 Manual batch edit → scoped temporary Auto validation → restore Manual。