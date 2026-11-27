# LongWorkMem-Bench

**工作场景长程记忆评测基准。** 同一句“继续处理”，在不同的工作历史中可能要求不同的行动：保留已关账的旧数字、遵守早先商定的版本冲突规则，或按开局侦察选择决赛构筑。评测在关键阶段冻结实际产物和环境状态，检查智能体是否正确沿用仍然有效的信息，以及为此付出的请求与计算成本。

## 已实现的进阶题

| Domain | 题目 | 核心场景与评分 | 使用入口 |
|---|---|---|---|
| Work | [W1 · 跨月采购关账与奖金分配](w1/) | 九轮连续办公。默认八级题按九个过程点（30 分）与四项业务结果（70 分）评分，核对关账、奖金、资金交接和跨期预留。 | [题目与成绩](w1/workflow.md) · [运行手册](w1/TEST.md) |
| Code | [C1 · 工时结算与保证金交割](c1/) | 七轮修改同一结算程序，第五、七轮换班，分别按签收时和轮末交付评分。 | [结算校准](c1/reports/c1-settlement-calibration.md) · [运行手册](c1/TEST.md) |
| Simulation | [S1 · 跨区器材联赛](s1/) | 十个赛区的八班公文交错发布，共八十轮。复核指定队伍的登记、器材配套与送达。 | [赛季校准](s1/reports/s1-circuit.md) · [运行手册](s1/TEST.md) |

每题的实现、测试、手册和研究报告集中在同名目录。各题仍从仓库根目录使用 `python -m w1.…`、`python -m c1.…` 和 `python -m s1.…`。公共测试入口、环境前提与分题命令见[测试指南](TEST.md)。此前整理的历史核查见[三题审核报告](docs/build/task-audit-20261127.md)。

## 本地验证

使用 Python 3.12。W1 工作簿评分还需 LibreOffice Calc，并确保 `soffice` 在 PATH 中。Docker 集成测试需相应题目的镜像和可写共享目录。以下命令执行本地检查，不调用模型 API。

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r w1/requirements.txt
python -m unittest discover -v
```

从 [rollout 目录](rollout/) 可查看后续正式运行的存储约定。当前测试阶段的原始会话、API 请求、快照和工具日志不入仓。各题的 `reports/` 收录实验说明及原有成绩资料。

## 研究与建设计划

首版目标约 **50 条完整工作会话**，覆盖 Work、Code、Simulation。正式长题规划为几轮到十几轮用户交互、约 1,000–2,000 次模型请求、几十 M 至几百 M token 累计输入，按试跑校准。各开发题的实测轮数、预算、种子和评分版本见题目文档。

| 阅读目的 | 文档 |
|---|---|
| 项目目标、会话结构与候选题 | [立项简报](docs/design/proposal.md) · [三类九道候选题](docs/design/session-candidates.md) |
| 调研依据与历史实验 | [基准构造及样本核查](docs/research/benchmark-notes.md) · [上下文管理观察](docs/research/prior-observations.md) · [采购样例复算](docs/research/workbuddy-reproduction.md) |
| 制作和验收新题 | [编题指南](docs/build/task-authoring.md) · [试跑计划](docs/build/pilot-plan.md) |
| 查看设计演进 | [历史草案 v0.1](docs/archive/pilot-v0.1.md) · [历史草案 v0.2](docs/archive/pilot-v0.2.md) |
