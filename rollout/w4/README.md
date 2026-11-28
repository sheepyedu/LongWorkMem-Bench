# W4 轨迹

Claude Code 与 DeepSeek V4.1 Flash 1017 的四场连续业务会话按版本保存。每场公开目录包含逐轮用户委托、助手回答、原生工具提案和实际工具输出；动作与上游用量分别按行列入 CSV。[基础版](deepseek-v4.1-flash/v1/) · [现场附页版](deepseek-v4.1-flash/v2/) · [夜班预约版](deepseek-v4.1-flash/v3/) · [四站调度版](deepseek-v4.1-flash/v4/) · [审计报告](../../docs/results/w4-release-20261128/)

在仓库根目录复制一场公开材料，核对指纹后解包，即可离线从邮件原件和快照复算。

```sh
dest=$(mktemp -d)
cp -R rollout/w4/deepseek-v4.1-flash/v2/. "$dest/"
(cd "$dest" && shasum -a 256 -c SHA256SUMS && tar -xzf artifacts.tar.gz)
python -m tasks.w4.pilot "$dest" --replay
```

实验机的私有目录 `rollout/w4/release-20261128/` 另存原始请求、失败、上游响应、会话和 MCP 工作日志。公开版保留可见业务交互，隐去账号、宿主路径、供应商内部推理和原生会话标识。v3 的原始记录在实验机 `rollout/w4/night-20261128/`。v4 原始记录在实验机 `rollout/w4/quota-20261128/`。各场分别使用各自冻结的合同。复评 v3 时需可运行同版 Calc 的 Docker 镜像。

四站版另有[逐项评分与扣分明细](../../docs/results/w4-quota-20261128/)。将上述命令的 `v2` 换成 `v4` 即可重放正式场；v4 复评同样需要 Docker Calc。
