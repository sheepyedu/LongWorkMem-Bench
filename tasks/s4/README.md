# S4 · Catan 跨局联赛

一个待测模型坐一席，Ash、Flint 和 Sail 是本地策略机器人。三局基础 Catan 开新会话、换地图与颜色，名称保持一致。六个独立练习局面随后打开。每个练习从固定中盘开始，模型控制当前一轮。模型能通过文本查看棋盘和自己的牌，完成建造、出价、确认交易，并维护自己的跨局笔记。

## 运行

使用仓库根目录、Python 3.12、Docker 和 Claude Code。游戏容器基于上游 Catanatron 的固定提交，容器以无网络、只读根文件系统和非特权用户运行。使用模型服务的主机进程与容器以标准输入输出交互。Claude Code 只连接桌面 MCP 的 `look`、`act`、`notes`，评分代码和指标表仅供评测端使用。

```sh
docker build -t longworkmem-catan:1 tasks/s4
S4_TEST_DOCKER=1 python -m unittest discover -v -s tasks/s4/tests -t .
python -m tasks.s4.pilot /path/to/new/run
python -m tasks.s4.grade /path/to/new/run
python -m tasks.s4.audit /path/to/new/run
```

Docker 镜像重建后的本机复评分可用 `grade --image longworkmem-catan:1 RUN` 指定重建镜像。记忆对照入口 `python -m tasks.s4.controls RUN NEW_CONTROL_DIR` 会从两桌独立快照比较保留笔记、空笔记和补齐事实三个条件，并保留各自轨迹。

`pilot` 使用宿主环境的 `ARK_API_KEY` 访问 DeepSeek V4.1 Flash 1017，关闭额外推理。评测端已有获授权的 Chat Completions 代理时可以传 `--upstream`。其他两条命令在既有轨迹上运行，无需模型接口。发生供应商或控制器故障的运行保留原始记录。模型连续两个推进段未产生棋局动作时记录停滞，在已经实际发生的状态上结算该桌。

首次盲测使用原题面。可通过 `pilot --prompt-version clarified RUN` 使用明确标注赛期和回合进度的变体，并在后续分析时独立记录。此变体沿用相同引擎和地图，适合与 `grade --first-road RUN` 联用。

每个完整棋局由多段连续 Claude Code 用户交互组成。每段最多推进本席七个普通回合，setup、弃牌和响应其他玩家交易按当前动作继续。完整棋局保留每个实际行动和回执。练习桌各自有独立手牌；前缀由引擎重放到固定状态。文本界面显示当前局面和合法动作，但桌面工具无法读取练习前缀、未来棋局或其他会话的原始历史。模型主动保存的笔记会跨会话保留。动作编号仅对指定事件位置有效。报价广播给三席，接受后需确认一个对手才实际交换资源。

## 评测端指标

| 维度 | 分值 | 证据 |
|---|---:|---|
| 整局经营 | 40 | 三盘平均。终局自有胜利点最多 25 分，胜局率最多 15 分。 |
| 跨局交易经验 | 20 | 两桌各 10 分。首次尝试成交且总成本合格 3 分，实际拿到砖且总成本合格 3 分，取得砖后实际铺路 4 分。 |
| 对手策略更新 | 20 | 两桌各 10 分，沿用相同动作评分。在已由引擎验证的状态中，旧报价被拒绝，更新后的合理成本仍可成交。 |
| 早期计划接续 | 20 | 两桌各 10 分。实际铺路 4 分，在先前指派的边铺路 6 分。 |

评分采用引擎回执和动作事件。冻结版 v1 的路线验收接受任一次铺对。复核选项 `--first-road` 可在同一轨迹上要求首条铺路即符合指派，单独生成 v1.1 明细，防止连续铺多条路覆盖目标。每项只计算本席实际执行的动作，练习前缀和其他席位无法得分；练习只计算当前回合。记忆笔记和文字自述不直接计分。牌数、棋盘、历史证据与同分合法动作均可检查，模型输出的 Markdown 和总结不需要按计分格式解析。无动作对照仍可显示既有游戏状态，六个练习项均为零分。

另外可以用 `python -m tasks.s4.grade RUN --calibration` 运行 v1.2 校准评分。该口径满分 60，降低整局胜负和常规铺路的权重，单独核验首报与实际成本。原始正式成绩仍使用 v1。[复评对照与加压设计](../../docs/results/s4-catan-20261128/scoring-calibration.md)

**设计边界。** 练习从已保存的局面开始，整局反映真实对手互动。当前版本的一个赛程只支持单个实例的难度判断。同行赛对照应交换同一席位和牌局种子，并在同一练习棋局分别比较自写记忆、空记忆和正确历史事实。跨局新会话与 Claude 原生压缩单列报告。参考轨迹受到上游 GPL-3.0-or-later 引擎启发，游戏规则和合法动作直接由 [Catanatron](https://github.com/bcollazo/catanatron/tree/ecf931181b9a65bb4116a2153fb78c16f1438e00) 执行。Docker 保留引擎及依赖的许可证。

## 续作与切桌实验

`catan-continuation-v1` 是单独的 20 分检查。A 桌固定于一段真实四人棋局，先铺主干，随后收到路线通知，继续铺支路、买入缺少的资源并完成定居点。复盘计算还原棋局状态、主动支出后的保留资源和真实动作。A 版在中间做只读进度确认，B 版切去独立棋局完成购砖、铺路与回合结束，再回到同一个 A 状态。两版同用一条原生 Claude 会话，桌面回执用桌号标识本次操作。两条历史（`keep` 与 `revise`）改变授权目标，保持当前棋盘和行动可见性一致。可选 `--opponent base` 保留原策略，默认 `cautious` 对照中 Ash 保留手里最后的砖。

```sh
docker build -t longworkmem-catan:continuation tasks/s4
python -m tasks.s4.continuation /path/to/new/run --arm single --case keep
python -m tasks.s4.continuation /path/to/another/run --arm switch --case keep
python -m tasks.s4.continuation /path/to/new/run --replay --image longworkmem-catan:continuation
python -m tasks.s4.audit /path/to/new/run
```

将 `--case` 改为 `revise` 即运行另一条历史。原始 v1 样题可继续按上文运行。续作试验的[A/B 结果与复评](../../docs/results/s4-continuation-20261128/)独立归档。


## 单桌长程资本工程

`catan-long-league-v1` 保持同一四人棋盘和同一个模型会话，包含 16 段用户交互。玩家从主干和分段交易开始，经路线修订、定居点交付、生产和资本筹措，最终使用早期授权升级城市。参评者可见棋盘邻接、港口、手牌、合法动作及每笔实际自愿支出后的小麦余量。后段不会重新给出早期城市节点。

正式试跑采用 `strategic` 对手。Ash 保留最后一张砖及两张矿石，Flint 结合公开胜利点和受影响的产出选择盗贼落点。维护对照可使用 `--opponent cautious`。`east`、`east-capital` 使用同一地图和路线修订，改变早期的城市授权。9 个评分检查点共 100 分，对局中的合法替代交易和补救路径可按交付得分。

```sh
docker build -t longworkmem-catan:long-league tasks/s4
python -m tasks.s4.long_league /path/to/new/run --case east
python -m tasks.s4.long_league /path/to/another/run --case east-capital
python -m tasks.s4.long_league /path/to/new/run --replay --image longworkmem-catan:long-league
python -m tasks.s4.audit /path/to/new/run
```

[单桌长程版试跑与对照](../../docs/results/s4-long-league-20261128/)单独保留历史版本。两次模型试跑采用同模型、同棋盘的配对授权，用量和压缩按实际回执汇报。
