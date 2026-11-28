# S4 轨迹

S4 使用 Claude Code 和 DeepSeek V4.1 Flash，三场 Catan 完整对局及六桌固定回放练习。真实竞赛、原生压缩和短记忆对照按各自的场次记录。

完整记录保存于实验机的 `rollout/s4/catan-v1-20261128/`。每场保存逐段委托、Claude Code 原始事件、上游请求与响应、本席操作日志、进程退出状态、阶段棋局和笔记快照。复评由固定引擎重放实际操作。结果报告与逐条审阅入口见 [S4 正式实测](../../docs/results/s4-catan-20261128/)。

## 公开复评

[复评包](catan-v1-20261128-replay.tar.gz)保存脱敏会话索引、逐段委托、全部桌面工具参数与结果、冻结局面。它与原场的游戏状态逐事件一致。先校验包，再用 Docker 重放。命令从仓库根目录运行。

```sh
(cd rollout/s4 && shasum -a 256 -c SHA256SUMS)
run=$(mktemp -d)
tar -xzf rollout/s4/catan-v1-20261128-replay.tar.gz -C "$run"
docker build -t longworkmem-catan:1 tasks/s4
python -m tasks.s4.grade "$run" --image longworkmem-catan:1
python -m tasks.s4.grade "$run" --image longworkmem-catan:1 --first-road
```

原始上游请求与响应、Claude Code 事件和六场对照保存在实验机，各有 `SHA256SUMS`。上游用量和逐条可见性以[审计索引](../../docs/results/s4-catan-20261128/)为公开证据。

## 续作与切桌

`continuation-20261128/` 在实验机保留四场原始运行及逐文件校验值。公开包提供逐段委托、桌面操作与回执、状态指纹和公开复评命令。[续作对照](../../docs/results/s4-continuation-20261128/)。
