# C1 运行与验收

所有命令均从仓库根目录执行。运行前创建主机侧目录 `mkdir -p runs/c1`。

## C1 工单事件库

C1 使用 Python 3.12 和标准库。准备本地 Docker 的 Python 镜像，运行器在每批会话开始时按镜像 ID 固定实际运行环境。macOS 开发机也可选择 Seatbelt。所有运行都使用新的目标目录。独立 Docker VM 若仅共享指定目录，请将运行路径和 `C1_TEST_ROOT` 设在可写共享目录内，并导出该 VM 的 `DOCKER_HOST`。凭证通过隐藏输入或 `ARK_API_KEY` 传给宿主。

```sh
docker pull python:3.12-slim
python -m unittest discover -v -p 'test_c1*.py'
C1_TEST_DOCKER=1 python -m unittest discover -v -p 'test_c1*.py'
python -m c1.reference runs/c1/c1-reference --variant B --backend docker
python -m c1.grade runs/c1/c1-reference --variant B --backend docker
python -m c1.pilot runs/c1/c1-smoke --smoke --variants A --limit 16
python -m c1.pilot runs/c1/c1-pair --variants A B --limit 1500
python -m c1.grade runs/c1/c1-pair/A --variant A --backend docker
python -m c1.review runs/c1/c1-pair/A
python -m c1.review runs/c1/c1-pair/A --turn 9
```

两轮联测实际创建 SQLite 表并跨轮回读随机编号。正式十二轮沿用同一个 Claude 会话，两个变体使用独立工作卷。第六轮的宿主作业在分片事务内退出，`fault.json` 和 `fault/` 保留代理收到通知前的现场。每轮结束的 `snapshots/N/` 包含完整源码、线上数据库、隔离清单、输出、笔记和实际收到的业务材料。复评在新副本中运行候选程序，真实检查历史查询、审核记录和冷启动重放。首次重建使用原始数据，第二次打乱可交换事件、重复发送并引入一个新实体。

| 检查点 | 分值 | 独立证据 |
|---|---:|---|
| 旧接口与迁移 | 15 | 第 1 轮原命令 CSV 回归，第 2 轮唯一编号恢复及歧义行清单 |
| 接入与版本 | 20 | 第 4 轮实体身份、乱序状态、重发与普通冲突 |
| 分片与切回 | 20 | 事务退出时的冻结现场、独立日志失败 ID、第 8 轮无遗漏且无重复 |
| 审批与历史 | 20 | 第 9 轮当前归属与批次处置，第 10 轮撤销范围与分版本历史 |
| 报表与灾备 | 25 | 第 11 轮部门计数、月末明细，第 12 轮交付与两次独立重放和旧调用方回归 |

按同一冻结件可重复判分。CSV 按字段读取，允许标准引号、BOM 和不同换行；公开契约要求顺序的输出检查排序。两个版本固定采用同一策略时，A、B 至少有一版的关键处置失败。除工程总分外，分别读第 9 轮当前归属、审批适用范围、审计与月末历史中的 14 分。宿主不能运行评分环境时，查看 `valid` 和 `infrastructure_errors`。

```sh
python -m c1.pilot runs/c1/c1-common --handoff --variants A
python -m c1.pilot runs/c1/c1-controls --controls-from runs/c1/c1-common/A/snapshots/8 --variants A B --limit 60
python -m c1.grade runs/c1/c1-controls/B-current --variant B --backend docker --control
```

公共交接只处理原先开放的业务。短对照各从同一份 R8 源码和数据库发起全新会话，在正常业务档案中还原本变体决议。提醒组还在第 9 轮委托中直接获得决议摘录。第 9 轮短对照满分 10。审阅时结合 `trace/turn-N.jsonl`、`tools-N.jsonl`、`api-*.json` 及冻结文件，区分复述、主动回查、已有实现和当前修改。

### C1 六轮工时结算

使用 Python 3.12、Claude Code 和上述 Docker 环境。两个上游须分别指定模型和各自的兼容端点，用隐藏输入传入对应凭证。为两个模型使用不同空目录，相同的种子、A/B、请求上限与签收窗口。

```sh
python -m c1.calibrate runs/c1/dispatch-model1 --level 2 --dispatch-after 4 --seeds 41 83 --model MODEL --url CHAT_COMPLETIONS_URL
python -m c1.settlement_grade runs/c1/dispatch-model1/41-A --backend docker
python -m c1.review runs/c1/dispatch-model1/41-A
```

每回合的第 4 条命令执行完即签收，提前结束则在结束时签收。可以批处理命令。轮末仍可修复。总分为签收成绩的 2/3 加轮末成绩的 1/3，两项单列。无签收窗口的等级 1、2 使用轮末交付。等级 2 含 192 对编号、9 份分片/批、9 组历史水位，要求按原凭证单位序号保存 FIFO 归属和分币。R2 当班签发人会影响 R5 撤令与 R6 归档。在限时签收版本，R3 起须使用此前保留的交接信息。空交、部分错行、顺序变化、新工单重跑及未按时交付分别检查。

等级 3 用相同工时来件再加第七轮保证金。第一、三、四轮窗口的分组、渠道、有效期和额度各自发布一轮；早期已占款在换版后继续占用。第七轮收到 720 件申请和 43 条重送，分别重演第 3、6、9 日。各冻结点中，前六轮占 75 分，第七轮按三个历史截止日的处置、占款与余额各给 7 分，另有 4 分新来件复跑。对比时核对相同委托、源文件、沙箱镜像与预算，并按 A/B 身份实际翻转的事件单列成绩。

```sh
python -m c1.calibrate runs/c1/guarantee-model1 --level 3 --dispatch-after 3 --seeds 101 149 --model MODEL --url CHAT_COMPLETIONS_URL
python -m c1.settlement_grade runs/c1/guarantee-model1/101-A > runs/c1/guarantee-model1/101-A/settlement-score-v2.json
python -m c1.settlement_compare runs/c1/guarantee-model1 runs/c1/guarantee-model2 --seeds 101 149
```

比较前为双方所有实例保存评分。运行 `C1_TEST_DOCKER=1 python -m unittest c1.tests.test_c1_settlement` 会实际在独立容器运行参考 CLI、静态交件和受损程序。参考解使用分段 FIFO 和逐日日历，评分器使用单位追踪和逐笔选择制度。UTF-8 BOM、合法行序变化可通过，空 JSON 对象、坏编码、额外重复行和错用最新授权均不会取得相应项分数。

三级运行加 `--rotate --dispatch-after 2` 可开两次通知过的换班：第 5、7 轮启用新的 Claude 身份和客户端目录。第一个 API 请求可验证没有上一班的 assistant/tool 消息；冻结工位仍保留。另可用 `python -m c1.settlement_diagnostics RUN` 对最终程序补送同一调拨的第二张有效撤令，单列稽核决定与总账，原评分保持可复算。
