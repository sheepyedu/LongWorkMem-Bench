# W1 跨月关账测试指南

## 单会话 W1 与模型比较

每个种子只发一个实例，默认八级、350 次请求预算，目标目录由运行器创建，包含这一场的九次截止快照。单个模型可直接取得完整成绩。需要比较模型时，各用同一个种子运行一次。

```sh
python -m w1.advanced runs/reference --reference --seed 431
python -m w1.pilot runs/dev-ds --seed 431
python -m w1.advanced runs/dev-ds --details
python -m w1.pilot runs/dev-qwen --seed 431 --model qwen3.8-flash
python -m w1.paired runs/dev-ds runs/dev-qwen
```

DeepSeek 使用方舟模型 `deepseek-v4-1-flash-261017` 和宿主 `ARK_API_KEY`。千问使用用户配置的 OpenAI 兼容网关 `DEEPSEEK_BASE_URL` 和该网关独立的 `DEEPSEEK_API_KEY`，也可以在被提示时无回显输入。两者共用 Claude Code、三种办公工具、材料、九轮截止与请求预算。每次使用新的运行目录。`w1.paired` 检查同题两模型的九个材料摘要、实际推理回执和 CLI 结束记录，正式八级按过程与业务结果汇总。可传入多个完整配对；开发和验证组分别执行。

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
python -m w1.pilot runs/connection --smoke --backend docker
python -m w1.pilot runs/first-close --backend docker --seed 431
python -m w1.grade runs/first-close
python -m w1.review runs/first-close --turn 7
```

命令中的目标目录可换成自选位置。使用新的目标目录可保留旧运行记录。输入上游密钥时终端无回显，也可通过 `ARK_API_KEY` 注入。运行器设置独立的 Claude Code 配置目录、清空内置工具和个人指令，只注册 shell、draft、deliver 三个办公工具。Claude Code 使用相同 session ID 继续后续轮次。本地适配层将 Messages 工具调用转换为指定 Ark 模型的 Chat Completions 请求，保留工具对应关系和后续调用所需的推理字段。上游密钥只留在宿主代理进程中。上游使用非流式回执，本地按 Claude 协议返回事件。CLI 的标价估算不能替代提供方账单。

每轮最多等待 30 分钟，单次办公命令限时 60 秒。请求预算按每场九轮会话计数。对比时记录 Claude 版本、模型 ID、后端和预算。完整的 `manifest.json`、`trace/`、`snapshots/1..9/`、`mail/` 和最终 `work/` 都在每条运行目录中。开发机运行目录放入仓库本地排除项，避免将日志和大文件加入 Git。

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
python -m s1.pilot runs/s1-smoke --backend docker --smoke --limit 30
python -m s1.pilot runs/s1-pair --backend docker --seed 31 --limit 150
python -m s1.pilot runs/s1-current --backend docker --control current --seed 31 --limit 30
python -m s1.pilot runs/s1-reminder --backend docker --control reminder --seed 31 --limit 30
python -m s1.grade runs/s1-pair/A
python -m s1.grade runs/s1-current/A
python -m s1.review runs/s1-pair/A
python -m s1.review runs/s1-pair/A --turn 7
```

若 Docker 使用非默认本地 socket，在运行器的环境中设置 `DOCKER_HOST`。镜像仅包含牌桌、模拟器和标准库，启动前按镜像 ID 校验游戏代码。比赛容器断网，根文件系统只读，挂载本场的 SQLite 目录供事务写入。CLI 的上游桥接、凭证、其他赛季、评分器和轨迹都在牌桌之外。开发机也可用 `--backend native` 运行相同 MCP 工具。

八轮的宿主检查包括揭幕站和第二站（7＋8）、邀请赛两小场（7＋8）、回主赛首次真正出牌和全站累计（10＋5）、统一组正式锁定的构筑在两手公开租借牌上能否达到 15 游戏分（30）、自由组两场实际晋级和终局付款（10＋10＋5）。每轮的比赛分是公开游戏规则。宿主检查的各项权重、两版答案和评分实现不发送给模型。冷启动用全新 Claude 会话和空笔记进入同一报名台，只评统一席位，分母 30。

在每条轨迹中按顺序读 `trace/prompt-N.txt`、`trace/turn-N.jsonl` 和 `trace/tools-N.jsonl`，用 `snapshots/N.json` 核实回复中的完成、得分、付费和报名陈述。`trace/api-*.json` 保存逐次请求与回执。独立复评使用冻结游戏材料和实际动作重放；新版本规则可能拒绝旧快照，复现原发布成绩应使用该次 manifest 标记的代码。输入损坏、快照缺失和成绩为零应分别检查。开发轨迹留在使用者的运行目录，不进入被测环境。

### S1 器材交接和换班记忆

`python -m unittest discover -p 'test_s1_relay*.py' -v` 检查每一档的 A/B、撤回和阶段有效期、部分分、受限交接簿参考解、异常回执和独立重放。在仓库根目录运行以下命令。环境变量 `ARK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_API_KEY` 仅供宿主桥接读取。

```sh
python -m s1.relay_pilot runs/relay-dev --models deepseek qwen --seeds 193 --level 1 --condition relay --direct-response --edition warehouse
python -m s1.relay_review runs/relay-dev/warehouse-L1-193-*
python -m s1.relay_review runs/relay-dev/warehouse-L1-193-* --compare
```

每个赛季目录必须是新的。每轮交叉核对 `trace/prompt-N.txt`、Claude 原始 JSONL、上游请求及返回、`receipt-N.json`。无法独立重放的赛季不参加模型对比。对照条件用 `continuous`、`current` 或 `evidence`。分数以四个阶段的整季百分制汇总，独立样本按种子计数。

## 进阶版验收

`python -m unittest tests.test_advanced tests.test_paired tests.test_erp_window` 检查九轮的可重复发布、A/B 唯一事实差异、参考全分、配对回执和远程工作窗口。业务负例位于 `tests/test_advanced_ledger*`、`tests/test_advanced_pay*` 和 `tests/test_advanced_mail*`。四级与五级发布相同文件，五级每轮的用户请求另告知作业额度。正式运行与比分命令沿用上面的例子，只需替换级别、种子和新的运行目录。窗口条件的报告还给出每轮准许的批数、实际受理数及窗口关闭回执数。

正式八级采用 13 个评分点。过程分依次为 3、4、3、3、4、3、3、4、3，证据依次取自首轮底稿、补件与首询、冻结与人事移交、会议简报、跨月续核、批准放行、双签调班、送审稿、实际回执与归档。四项结果分别核验采购关账（18）、个人实发及活公式（20）、清算与授权交接（12）、跨期预留及上一日实报追调（20）。同一评分点内各项核验的完成比例取算术平均，每个底层核验仅计入一个评分点。预留按整案核对，末轮以第八轮实际提交为基数；伪造回执、空文件和单纯口头宣称均不能证明完成。过程和结果可独立得部分分。

`python -m unittest tests.test_w1_single -v` 核验单会话启动、满分、漏交简报和单案多字段错误的局部扣分。开发难度 0–7 仍可显式选用。旧八级快照可用 `python -m w1.advanced RUN --legacy` 复原历史分数。

W1 工作簿回归覆盖带引号的拼接分隔符，允许按“项目|员工”匹配，继续检查外部公式、调用及关系。配对回执覆盖提供方正常结束但工具 JSON 格式错误的记录，与输出截断分别统计；两种情况均须有同轮同请求的成功重试。验证可运行 `python -m unittest tests.test_grade tests.test_paired`。

### S1 连续跨区长赛季

在仓库根目录运行；双模型沿用器材交接版的宿主环境变量。每次选新输出目录。所有比赛材料和原始提交均按轮冻结。

```sh
python -m unittest tests.test_s1_circuit -v
python -m s1.circuit runs/circuit --desks 10 --qualifiers 2 --level 2 --seeds 2831
python -m s1.circuit_review runs/circuit/Q*
```

`--history regional` 为每区独立保留一个会话，区序和订单与连续条件一致。复评逐轮核对系统提示、用户公文、Claude 会话编号、真实上游回复及配发记录，分别列示实测累计输入、首次提交输入、单次峰值与缓存命中。开发种子及独立验证结果见 `docs/research/s1-circuit.md`。

正式混合赛的运行参数为 `--desks 10 --qualifiers 2 --level 2`。中途主动整理资料的短对照使用 `--history handover`，在赛季中点由模型用 note 提交最多 5,500 字符的摘要，下一轮新会话只能带入实际留存的摘要。连续主赛没有这个切换。

同场复测 GPT-6.1 Sol 可执行 `python -m s1.circuit runs/gpt-sol --models gpt-6.1-sol --desks 10 --qualifiers 2 --level 2 --seeds 39107 88469`。宿主读取 `OPENAI_BASE_URL` 与 `OPENAI_API_KEY`。该路由最低支持 low 推理档，审计要求实际发送此档位、返回指定模型并能从终端提交重建分数。

长赛季每个模型和种子只运行一次，默认模型为 DeepSeek。每区第 1、2、3、6 班各登记两队的四个字段。开幕后优先抽查本班撤回或批准涉及的队伍，适用范围与截止时点由当班任务指定。四班各占 7.5 分，各区等权。缺字段只失去对应分数，空回复为零，笔记和文字声明不计分。第 4、5、7、8 班分别占 14、10.5、28、17.5 分，照实际回执逐队验收器材及送达。复评报告列出两部分分数；grade.json 保留每区、每班、每队的实际值与期望值。旧 manifest 沿用原公文、原权重。
