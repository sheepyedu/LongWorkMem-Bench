# Rollout 轨迹

## GPT-6.1-sol

以下四场使用 Codex app-server、`low` 推理档和公开实例 `17217/A`。点击「逐轮轨迹」后，`prompt-N.txt` 是用户委托，`turn-N.jsonl` 按发生顺序保存回答、工具参数和返回值、用量及轮末状态；`threads.jsonl` 记录换班和工具配置。

| 题目与运行条件 | 轮数 | 得分 / 100 | 逐轮轨迹 | 评分与冻结交付 |
|---|---:|---:|---|---|
| W1 · 采购关账与工资分配 | 9 | 87.525 | [逐轮轨迹](w1/gpt-6.1-sol/17217-A/trace/) | [逐项评分](w1/gpt-6.1-sol/17217-A/grade.json) · [交付包](w1/gpt-6.1-sol/17217-A/artifacts.tar.gz) |
| C1 · 初次运行 | 7 | 32.95 | [逐轮轨迹](c1/gpt-6.1-sol/17217-A/trace/) | [逐项评分](c1/gpt-6.1-sol/17217-A/grade.json) · [交付包](c1/gpt-6.1-sol/17217-A/artifacts.tar.gz) |
| C1 · 修正权限提示后 | 7 | 100 | [逐轮轨迹](c1/gpt-6.1-sol/17217-A-permissions-v2/trace/) | [逐项评分](c1/gpt-6.1-sol/17217-A-permissions-v2/grade.json) · [交付包](c1/gpt-6.1-sol/17217-A-permissions-v2/artifacts.tar.gz) |
| S1 · 跨区器材联赛 | 80 | 100 | [逐轮轨迹](s1/gpt-6.1-sol/17217-A/trace/) | [逐项评分](s1/gpt-6.1-sol/17217-A/grade.json) · [交付包](s1/gpt-6.1-sol/17217-A/artifacts.tar.gz) |

每场目录还包含 `manifest.json`、公开文件的 `SHA256SUMS`。交付包内，W1 包括最终工位、九轮快照和邮箱记录，C1 包括最终工位和七轮快照，S1 包括八十轮实际受理的回单。公开轨迹将原生会话和消息标识替换为场内一致的代号，略去账户遥测、宿主临时路径、推理正文、流式增量及重复事件。业务题面、回答、工具输入输出和评分证据保留；原始档案指纹另见[运行结果](../docs/results/codex-gpt61sol-20261127/runs.csv)。

### 离线复评示例

从仓库根目录将一场公开轨迹复制到临时目录，核对文件并解包后，运行同一评分器：

```sh
run=$(mktemp -d)
cp -R rollout/s1/gpt-6.1-sol/17217-A/. "$run/"
(cd "$run" && shasum -a 256 -c SHA256SUMS && tar -xzf artifacts.tar.gz)
python -m tasks.codex_bench s1 "$run" --replay
```

W1、C1 替换相应题号和目录即可。W1 需宿主 LibreOffice Calc；C1 需 Docker 和指定的 Python 镜像，独立 VM 的 `C1_TEST_ROOT` 应指向双方可写的共享目录。[环境准备](../README.md#运行与验证)

## C2 · Claude Code + DeepSeek 4.1 Flash

[正式场和诊断场](c2/)均保留八轮业务交互及可独立复评的冻结交付。

## DeepSeek 与千问历史批次

`advanced-audit-20261127-203015` 按题归档，每题八场。该批的完整记录保存在实验机 `rollout/<题号>/<批次>/<运行>/`，GitHub 提供[逐场分数、用量和原始档案校验值](../docs/results/advanced-audit-20261127/runs.csv)。

## S4 · Claude Code + DeepSeek 4.1 Flash

[原场轨迹、审计索引与离线复评](s4/)覆盖三场 Catan 及六桌固定练习。
