# W1 跨月关账测试指南

## 进阶题和双模型复跑

`--level 0` 保留原九轮开发题。进阶题的 `--seed` 确定业务数字、部分路由和签报。同种子、同级别的 A/B 只改第二轮 HR-0628 的生效月。运行器把每轮任务、当时可见的只读资料摘要、请求次数和办公镜像 ID 记入宿主 manifest。

```sh
python -m w1.advanced runs/advanced-reference --reference --level 2 --seed 431 --variant A
python -m w1.pilot runs/dev-ds --backend docker --level 2 --seed 431 --variants A --limit 350
python -m w1.pilot runs/dev-qwen --backend docker --level 2 --seed 431 --variants A --limit 350 --model qwen3.8-flash
python -m w1.advanced runs/dev-ds/A
python -m w1.paired runs/dev-ds/A runs/dev-qwen/A
```

DeepSeek 使用方舟模型 `deepseek-v4-1-flash-261017` 和宿主 `ARK_API_KEY`。千问使用用户配置的 OpenAI 兼容网关 `DEEPSEEK_BASE_URL` 和该网关独立的 `DEEPSEEK_API_KEY`，也可以在被提示时无回显输入。两者共用 Claude Code、三种办公工具、材料、九轮截止与请求预算。每次使用新的运行目录。`w1.paired` 检查同题两模型的九个材料摘要、实际推理回执和 CLI 结束记录，再汇总采购、薪酬和投递三个部分的成绩。可传入多个完整配对；开发和验证组分别执行。

## 本地准备

需要 Python 3.12、openpyxl 和 LibreOffice Calc。将 `soffice` 加入 PATH，或将环境变量 `W1_SOFFICE` 指向可执行文件。跑模型时还需 Claude Code CLI。正式数据与轨迹目录使用独立空目录，每条会话占一个子目录。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-w1.txt
soffice --version
python -m unittest discover -v
```

分组测试覆盖材料释放和 A/B 单字段差异、真实邮箱附件与不可变快照、两套参考解、等价表格、金额与归属反例、提前发放、虚构回执、损坏文件和活公式重算。macOS 还会测试系统沙箱的中性目录、输入写保护、宿主文件和网络访问限制。

## 离线走完整流程

```sh
python -c 'from pathlib import Path; from w1.reference import run_reference; run_reference(Path("runs/reference-A"), "A")'
python -m w1.grade runs/reference-A A
```

参考实现逐轮读取已释放材料，经同一草稿和发送接口交付，再使用独立参考账复评。A、B 参考路径各应得 100 分。对只改外观、行序和等价公式的交付也应满分。在没有 Calc 的环境中，检查器会在 `infrastructure_anomalies` 登记重算环境缺失，不能把这次结果当作完整成绩。

## 用 Claude Code 实跑

Linux/macOS 可使用 Docker。镜像包含 Python、openpyxl 和 LibreOffice Calc，代理可以用 `soffice --headless` 对副本做真实重算。镜像构建只读 Dockerfile，运行时容器挂载单个办公室的工作盘，业务输入只读，out、notes、scratch 可写。容器不挂载仓库、宿主套接字、运行轨迹或评分材料，网络禁用。每次命令在干净进程执行，同一会话保留工作卷。如果 macOS 虚拟机只挂载选定目录，将 `W1_TEST_ROOT` 设为该挂载下可写的测试目录，同时把运行路径放在同一挂载中。macOS 也可用 `--backend seatbelt`，使用系统沙箱和一个中性临时工作目录。

```sh
docker build -t longworkmem-office:1 - < w1/Office.Dockerfile
W1_TEST_DOCKER=1 python -m unittest tests.test_docker -v
python -m w1.pilot runs/connection --smoke --variants A --backend docker
python -m w1.pilot runs/first-pair --backend docker --variants A B --limit 1500
python -m w1.grade runs/first-pair/A A
python -m w1.grade runs/first-pair/B B
python -m w1.review runs/first-pair/A
python -m w1.review runs/first-pair/B --turn 7
```

命令中的目标目录可换成自选位置。使用新的目标目录可保留旧运行记录。输入上游密钥时终端无回显，也可通过 `ARK_API_KEY` 注入。运行器设置独立的 Claude Code 配置目录、清空内置工具和个人指令，只注册 shell、draft、deliver 三个办公工具。Claude Code 使用相同 session ID 继续后续轮次。本地适配层将 Messages 工具调用转换为指定 Ark 模型的 Chat Completions 请求，保留工具对应关系和后续调用所需的推理字段。上游密钥只留在宿主代理进程中。上游使用非流式回执，本地按 Claude 协议返回事件。CLI 的标价估算不能替代提供方账单。

每轮最多等待 30 分钟，单次办公命令限时 60 秒。请求预算按每个变体单独计数。对比时记录 Claude 版本、模型 ID、后端和预算。完整的 `manifest.json`、`trace/`、`snapshots/1..9/`、`mail/` 和最终 `work/` 都在每条运行目录中。开发机运行目录放入仓库本地排除项，避免将日志和大文件加入 Git。

## 检查点

| 阶段 | 满分 | 证据 |
|---|---:|---|
| 建立底账 | 15 | 第一轮初版底表与待认领占 4 分，第二轮按补件后的采购与发票关联、跨导出去重及待认领分别计 4、4、3 分 |
| 六月关账和临时简报 | 20 | 第三轮冻结版，第四轮逐行异常和分类、去重计数 |
| 切回与放行 | 20 | 报送时与后续各轮的历史快照，第五轮补件后当前账，第六轮书面放行及批准前记录 |
| 员工奖金 | 25 | 第七轮项目员工明细、当期共享工时归属、逐人截分及尾差 |
| 重算和实际分发 | 20 | 第七轮和第九轮工作簿各验基线、逐个员工改工时、逐个项目改池。用第八轮草稿、第九轮真实附件与回执核验分发，查全会话提前拟发奖金件和实际投递 |

先看有效性、单项原因和证据路径，再看总分。严格通过要求 100 分、各依赖通过且没有基础设施异常。HR 配对通过要求 A、B 各自的 E07 工时和金额在第七轮和最终交付均正确。一致性检查将同一个上游错误与后续动作分开，例如错误但如实保存的一张旧报表仍可能获得保存分。自然语言回复中超出证据的断言由逐条轨迹审阅另记。

## 复评时如何读轨迹

1. 读每轮的 `prompt-N.txt` 和 `turn-N.jsonl`，按顺序核对模型陈述、实际工具参数、工具结果和最终回复。`w1.review --turn N` 可按行号展开。
2. 对数量、授权、发送成功和公式可重算等陈述分别查冻结表、投递日记和 Calc 结果。保留先出错后修正的时间点。
3. 核对实际发给上游的工具清单和消息。复核宿主隔离探针，以及 `w1.review` 标记的私有路径或评分标识。命中特定文字本身不能证明数据已被读出。
4. 将每轮请求与 `manifest.json` 的序号和计数核对。`missing_request_files` 列出整份缺失的已登记请求，`attempts_without_usage` 列出有请求记录却缺用量的尝试。`shell_failures` 给出非零退出的工具结果行号，MCP 协议错误另列。某条复合 shell 命令最终返回 0 时，中间步骤仍可能失败，须查看实际输出或打开改值后的文件。
5. 逐请求汇总真实 usage、单请求峰值和缓存输入。缺少回执、主动停止、基础设施异常和正常九轮完成分别登记。在相同快照上重评不发出新模型请求。

## 在奖金使用点做短对照

```sh
python -m w1.controls runs/short-controls --backend docker
```

命令保留第六轮参考工作现场，再以相同条件启动四个独立的第七轮会话。两版各运行一次“只给当前现场”和一次“额外给出批复中的日期”。两组均可搜索已开放的邮箱。每条使用 50 次请求上限。各自的 `grade-cp4.json` 只汇报本轮 25 分、E07 的工时与金额，以及未受本轮委托的草稿和实际投递。用 `python -m w1.review RUN --turn 7` 区分主动回查、使用提示和未经授权的操作。

## S1 跨幕卡牌联赛

S1 的游戏、评分和回放只依赖 Python 3.12 标准库。Claude Code CLI 和 Ark 密钥供真实推理使用；密钥通过隐藏终端输入或环境变量 `ARK_API_KEY` 提供。每次试跑使用新的目标目录。以下在仓库根目录执行。

```sh
python -m unittest discover -p 'test_s1*.py' -v
COPYFILE_DISABLE=1 tar --format ustar -C s1 -cf - Table.Dockerfile __init__.py game.py table.py | docker build -t longworkmem-table:1 -f Table.Dockerfile -
python -m s1.pilot runs/s1-smoke --backend docker --smoke --variants A --limit 30
python -m s1.pilot runs/s1-pair --backend docker --variants A B --seed 31 --limit 150
python -m s1.pilot runs/s1-current --backend docker --control current --variants A B --seed 31 --limit 30
python -m s1.pilot runs/s1-reminder --backend docker --control reminder --variants A B --seed 31 --limit 30
python -m s1.grade runs/s1-pair/A
python -m s1.grade runs/s1-current/A
python -m s1.review runs/s1-pair/A
python -m s1.review runs/s1-pair/A --turn 7
```

若 Docker 使用非默认本地 socket，在运行器的环境中设置 `DOCKER_HOST`。镜像仅包含牌桌、模拟器和标准库，启动前按镜像 ID 校验游戏代码。比赛容器断网，根文件系统只读，挂载本场的 SQLite 目录供事务写入。CLI 的上游桥接、凭证、其他赛季、评分器和轨迹都在牌桌之外。开发机也可用 `--backend native` 运行相同 MCP 工具。

八轮的宿主检查包括揭幕站和第二站（7＋8）、邀请赛两小场（7＋8）、回主赛首次真正出牌和全站累计（10＋5）、统一组正式锁定的构筑在两手公开租借牌上能否达到 15 游戏分（30）、自由组两场实际晋级和终局付款（10＋10＋5）。每轮的比赛分是公开游戏规则。宿主检查的各项权重、两版答案和评分实现不发送给模型。冷启动用全新 Claude 会话和空笔记进入同一报名台，只评统一席位，分母 30。

在每条轨迹中按顺序读 `trace/prompt-N.txt`、`trace/turn-N.jsonl` 和 `trace/tools-N.jsonl`，用 `snapshots/N.json` 核实回复中的完成、得分、付费和报名陈述。`trace/api-*.json` 保存逐次请求与回执。独立复评使用冻结游戏材料和实际动作重放；新版本规则可能拒绝旧快照，复现原发布成绩应使用该次 manifest 标记的代码。输入损坏、快照缺失和成绩为零应分别检查。开发轨迹留在使用者的运行目录，不进入被测环境。

## 进阶版验收

`python -m unittest tests.test_advanced tests.test_paired tests.test_erp_window` 检查九轮的可重复发布、A/B 唯一事实差异、参考全分、配对回执和远程工作窗口。业务负例位于 `tests/test_advanced_ledger*`、`tests/test_advanced_pay*` 和 `tests/test_advanced_mail*`。四级与五级发布相同文件，五级每轮的用户请求另告知作业额度。正式运行与比分命令沿用上面的例子，只需替换级别、种子和新的运行目录。窗口条件的报告还给出每轮准许的批数、实际受理数及窗口关闭回执数。

七、八级共有 84 个计分项，另有 A/B 双边对照。在同一个种子上将两个模型的 A、B 共四个目录传给 `w1.paired`，查看 `memory_counterfactual` 中两边都处理正确的应变案件和应保持案件。重复提交同一个版本会失去应变案件正确数。单轮短对照可运行 `python -m w1.memory_control runs/reserve-short --turn 8 --seed 431 --variant A`；千问另选新目录并加 `--model qwen3.8-flash`。只给当前现场与附三次历史授权原文的两组，从相同参考交接状态开始，输出逐字段和整案正确数，独立于九轮正式成绩。

## C1 工单事件库

C1 使用 Python 3.12 和标准库。准备本地 Docker 的 Python 镜像，运行器在每批会话开始时按镜像 ID 固定实际运行环境。macOS 开发机也可选择 Seatbelt。所有运行都使用新的目标目录。独立 Docker VM 若仅共享指定目录，请将运行路径和 `C1_TEST_ROOT` 设在可写共享目录内，并导出该 VM 的 `DOCKER_HOST`。凭证通过隐藏输入或 `ARK_API_KEY` 传给宿主。

```sh
docker pull python:3.12-slim
python -m unittest discover -v -p 'test_c1*.py'
C1_TEST_DOCKER=1 python -m unittest discover -v -p 'test_c1*.py'
python -m c1.reference runs/c1-reference --variant B --backend docker
python -m c1.grade runs/c1-reference --variant B --backend docker
python -m c1.pilot runs/c1-smoke --smoke --variants A --limit 16
python -m c1.pilot runs/c1-pair --variants A B --limit 1500
python -m c1.grade runs/c1-pair/A --variant A --backend docker
python -m c1.review runs/c1-pair/A
python -m c1.review runs/c1-pair/A --turn 9
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
python -m c1.pilot runs/c1-common --handoff --variants A
python -m c1.pilot runs/c1-controls --controls-from runs/c1-common/A/snapshots/8 --variants A B --limit 60
python -m c1.grade runs/c1-controls/B-current --variant B --backend docker --control
```

公共交接只处理原先开放的业务。短对照各从同一份 R8 源码和数据库发起全新会话，在正常业务档案中还原本变体决议。提醒组还在第 9 轮委托中直接获得决议摘录。第 9 轮短对照满分 10。审阅时结合 `trace/turn-N.jsonl`、`tools-N.jsonl`、`api-*.json` 及冻结文件，区分复述、主动回查、已有实现和当前修改。

### C1 六轮工时结算

使用 Python 3.12、Claude Code 和上述 Docker 环境。两个上游须分别指定模型和各自的兼容端点，用隐藏输入传入对应凭证。为两个模型使用不同空目录，相同的种子、A/B、请求上限与签收窗口。

```sh
python -m c1.calibrate runs/dispatch-model1 --level 2 --dispatch-after 4 --seeds 41 83 --model MODEL --url CHAT_COMPLETIONS_URL
python -m c1.settlement_grade runs/dispatch-model1/41-A --backend docker
python -m c1.review runs/dispatch-model1/41-A
```

每回合的第 4 条命令执行完即签收，提前结束则在结束时签收。可以批处理命令。轮末仍可修复。总分为签收成绩的 2/3 加轮末成绩的 1/3，两项单列。无签收窗口的等级 1、2 使用轮末交付。等级 2 含 192 对编号、9 份分片/批、9 组历史水位，要求按原凭证单位序号保存 FIFO 归属和分币。R2 当班签发人会影响 R5 撤令与 R6 归档。在限时签收版本，R3 起须使用此前保留的交接信息。空交、部分错行、顺序变化、新工单重跑及未按时交付分别检查。

等级 3 用相同工时来件再加第七轮保证金。第一、三、四轮窗口的分组、渠道、有效期和额度各自发布一轮；早期已占款在换版后继续占用。第七轮收到 720 件申请和 43 条重送，分别重演第 3、6、9 日。各冻结点中，前六轮占 75 分，第七轮按三个历史截止日的处置、占款与余额各给 7 分，另有 4 分新来件复跑。对比时核对相同委托、源文件、沙箱镜像与预算，并按 A/B 身份实际翻转的事件单列成绩。

```sh
python -m c1.calibrate runs/guarantee-model1 --level 3 --dispatch-after 3 --seeds 101 149 --model MODEL --url CHAT_COMPLETIONS_URL
python -m c1.settlement_grade runs/guarantee-model1/101-A > runs/guarantee-model1/101-A/settlement-score-v2.json
python -m c1.settlement_compare runs/guarantee-model1 runs/guarantee-model2 --seeds 101 149
```

比较前为双方所有实例保存评分。运行 `C1_TEST_DOCKER=1 python -m unittest tests.test_c1_settlement` 会实际在独立容器运行参考 CLI、静态交件和受损程序。参考解使用分段 FIFO 和逐日日历，评分器使用单位追踪和逐笔选择制度。UTF-8 BOM、合法行序变化可通过，空 JSON 对象、坏编码、额外重复行和错用最新授权均不会取得相应项分数。
