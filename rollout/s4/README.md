# S4 · 40 轮最终版轨迹

两场都从同一棋局开始，均完成 40 轮。下表按最终评分器重新计算。输入包含缓存，输出和输入分别统计。

| 运行 | 经营分 | 采购 | 城市 | 输入 token | 输出 token | 原生压缩 |
|---|---:|---|---|---:|---:|---:|
| [DeepSeek V4.1 Flash + Claude Code](deepseek-flash-claude/) | 62.5 | 4 木换 1 砖 | 第 15 轮提前建在 21 | 15,722,164 | 36,737 | 1 |
| [GPT-6.1-terra + Codex](gpt61terra-codex/) | 76.5 | 1 木换 1 砖 | 委任期缺一麦，未建城 | 18,851,675 | 7,325 | 0 |

每个目录含冻结分项、用量和离线复评包。两包均保存逐轮题面、实际桌面操作、工具回执及状态指纹。DeepSeek 包内附逐轮答复、204 份模型请求与响应及实际采用的压缩摘要。Codex 包内含逐轮原生业务工具事件、答复和用量。完整宿主原始日志另存实验机。每种组合各一场。

## 从空目录复评

```sh
(cd rollout/s4 && shasum -a 256 -c SHA256SUMS)
docker build -t longworkmem-s4:40 tasks/s4
for model in deepseek-flash-claude gpt61terra-codex; do
  run=$(mktemp -d)
  tar -xf "rollout/s4/$model/replay.tar.xz" -C "$run"
  python -m tasks.s4 "$run" --replay
  cmp "$run/grade.json" "rollout/s4/$model/grade.json"
done
```

[正式题面与评分规则](../../tasks/s4/)

解包后可用 `python -m tasks.s4.audit "$run"` 审计 DeepSeek 轨迹，或用 `python -m tasks.s4.codex_audit "$run"` 审计 Codex 轨迹。
