# LongWorkMem-Bench

工作场景长程记忆评测基准。每题是一条连续工作流程，按实际文件、工具回执和环境状态评分。公开协议 `public-v1` 固定 **17217/A**；各模型收到相同的初始材料和业务规则，独立会话保留各自的后续交付。

| Domain | 题目 | 检查什么 |
|---|---|---|
| Work | [W1 · 跨月采购关账与奖金分配](tasks/w1/) | 九轮内冻结六月报送件，处理七月调整，并据先前批复办理工资、资金和预留。 |
| Work | [W4 · 售后手册发布与历史勘误](tasks/w4/) | 十二轮日夜班接续，按冻结邮件、客户异议和实际重算的预约表核验历史追溯与补救。 |
| Code | [C1 · 工时结算与保证金交割](tasks/c1/) | 修改同一程序，在第 5、7 轮换班，按轮末交付和新来件复跑评分。 |
| Code | [C2 · 客户身份迁移与故障续投](tasks/c2/cohorts/) | 十轮维护旧邀请和新订阅，处理限域撤回、数据盘回滚与客户实际签收。[前版](tasks/c2/evolution/) |
| Simulation | [S1 · 跨区器材联赛](tasks/s1/) | 十区八十轮，第 40 轮交接自写摘要；从赛事单据复核登记、器材配套和送达。 |
| Simulation | [S4 · Catan 跨局联赛](tasks/s4/) | 三场真实 Catan 对局及六个练习，测试跨局交易经验、更新旧经验和局内计划接续。 |

## 运行与验证

从仓库根目录使用 Python 3.12。每道题的 README 包含 Docker 环境、运行命令和复评入口。模型新作答需要相应推理服务；已有轨迹复评及以下回归测试可离线运行。宿主需有 LibreOffice Calc 完成 W1 工资簿测试。

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r tasks/w1/requirements.txt -r tasks/c2/requirements.txt
python -m unittest discover -v
```

默认无模型请求次数上限。额外试跑预算、W1 的 ERP 限批以及 C1 的提前取件各自单列。材料指纹、评分边界与测量局限见[公开协议](docs/protocol.md)。

### Codex 原生运行

W1、C1、S1 支持 Codex app-server；C2 和 W4 目前使用 Claude Code。安装支持动态工具和空环境列表的 Codex CLI（已测版本见实测记录），先执行 `codex login`，再按各题 README 准备 Docker 镜像。运行目录应为新路径，W1/C1 使用 Docker 可读写的共享目录。

```sh
python -m tasks.codex_bench w1 rollout/w1/codex/17217-A &
python -m tasks.codex_bench c1 rollout/c1/codex/17217-A &
python -m tasks.codex_bench s1 rollout/s1/codex/17217-A &
wait
```

默认模型 `gpt-6.1-sol`、推理档 `low`，可通过 `--model`、`--effort` 显式选择。W1 开放三种办公动作，C1 开放工位 shell，S1 只接收回单。每场保存原生线程与逐轮 app-server 事件、工具往返、快照或单据及成绩。通过同一命令加 `--replay` 从轨迹复核；复评沿用对应 Docker 环境，W1 另需宿主 Calc。token 使用量按每个原生线程的最后一次累计回执求和。`usage_updates` 是 Codex 返回的用量事件数，网络重试和供应商计费明细需另行观测。

## 实测数据

[24 场双模型结果与逐题分差归因](docs/results/advanced-audit-20261127/)给出六组原分、token、每个阶段对均分偏差的贡献及对应实例。该批使用四个配对业务种子与当时的试跑配置。完整轨迹按题归档，公开索引附校验值。[归档约定](rollout/)

[GPT-6.1-sol 四场公开轨迹](rollout/#gpt-61-sol)覆盖 W1、C1、S1 三场并行实测，以及修正权限说明后的 C1 追加场。可在线查看每轮题面、回答、工具操作和结果，也可下载冻结交付并离线复评。[分数与用量](docs/results/codex-gpt61sol-20261127/)

[C2 客户迁移版工程验收](docs/results/c2-cohorts/)给出六条脚本对照、逐项扣分及旧轨迹可复用范围。

[C2 评分校准](docs/results/c2-case-calibration/)给出十轮逐项得失与同一份代码的配对验收。沿用原题面，降低常规排期和首发的权重，增加升级、回退和历史签收的独立证据。

[C2 十轮进阶版首场审计](docs/results/c2-evolution-20261128/)记录 DeepSeek 的 97.6471 分、三次原生压缩、两处交付偏差与题面勘误。当前实测仍有明显高分风险。

[W4 夜班预约版首场盲测](docs/results/w4-night-20261128/)新增十二笔独立异议以及三个交班日的工作簿变更重算。

[W4 两版开发及 DeepSeek 盲测](docs/results/w4-release-20261128/)记录基础场、现场附页加难场、两版冻结成绩和可重放轨迹。[按实际履约复评](docs/results/w4-release-20261128/outcome-calibration.md)对照 W1 分析得失、离线变异和下一版工作环境。

[C2 首次开发与盲测](docs/results/c2-calendar-20261128/)记录八轮日历发布任务的环境验收、真实轨迹、正反例和评分审计。

[S4 Catan 首次盲测与逐条审计](docs/results/s4-catan-20261128/)覆盖 19 段、548 次请求、三次原生压缩及六个短对照。正式成绩 71.5/100，代码与题面复核边界见审计。

[S4 双桌续作配对盲测](docs/results/s4-continuation-20261128/)独立记录增强难度后的单桌与切桌比较、深度审计和离线复评。

[S4 单桌长程资本工程](docs/results/s4-long-league-20261128/)将连续会话扩展到 16 段，加入分段交易、路线授权修订和延迟兑现的城市升级。

## 当前观察与局限

| 实测观察 | 解读 |
|---|---|
| GPT-6.1-sol 在修正后的 C1 和 S1 各有一场满分；较早的 C1 测试中，DeepSeek 和千问在部分实例的轮末交付也达到过满分。 | C1 对强模型的区分空间可能有限。S1 中，GPT 用 5,458 字符准确交接了十区底册及有效批准单。每种新配置仅跑一次，稳定性仍待同条件重复验证。 |
| 两次 GPT 满分场的单次输入峰值均约 2.2 万 token；四场均未观测到原生压缩。 | 已验证模型可以在换班后利用工作文件或摘要继续交付。累计输入包含反复传入的历史；要判断压缩后的依赖保持能力，还需要实际跨过压缩事件的检查点。 |
| C1 首场中，模型把客户端的只读提示理解为 Docker 工位不可写，缺少两轮交件，得 32.95 分；修正提示后追加一场得 100 分。 | 工具权限说明会影响交付。旧批次还有提前签收、试跑预算和登记解析器差异；跨批比较要列出这些条件，并保留异常场的原始得分。 |

## 新题怎样验收

Work 类出题人可以直接使用 [work-bench skill](.agents/skills/work-bench/SKILL.md)。其中收录了 [SWE-Milestone 等基准的构造与计分依据](.agents/skills/work-bench/references/milestones-and-reliability.md)、同场历史附件样例，以及可离线运行的[客观评分](.agents/skills/work-bench/references/scoring.md)和[重复试跑校准](.agents/skills/work-bench/references/calibration.md)工具。

1. **验证早期信息确实影响后期交付。** 为一条依赖准备成对材料，只改一项早期授权或签收回执；参考解应只改变受影响的后续账目、订单或操作。让模型自己的实际交付参与决定下一步，例如根据已发数量办理补发。
2. **验证延迟依赖。** W4 在同一会话中安排首次使用、隔轮沿用、局部更新和历史追溯。其他题可按研究问题选用正确前置状态的短对照。分别记录首次交付、错误恢复和最终结果，模型按真实回执正确补救时应获得相应分数。
3. **同时验证区分度和稳定性。** 固定题面、工具权限、交接方式和评分器，每个模型独立重复运行。并列报告分项得分、范围和失败位置；优先保留模型间差距可重复、且能从具体交付解释的题目。先排查提示歧义、格式误判或单点扣分过大。
4. **分别测量工作量与上下文压力。** 记录关键约束何时出现、何时再次使用，中间经过哪些任务切换、换班或压缩。结合单次输入峰值、累计用量、实际整理动作和后续交付判断难度。

完整评分口径与对照设计见[公开协议](docs/protocol.md)。
