# S1 运行与验收

所有命令均从仓库根目录执行。运行前创建主机侧目录 `mkdir -p runs/s1`。

## S1 跨幕卡牌联赛

S1 的游戏、评分和回放只依赖 Python 3.12 标准库。Claude Code CLI 和 Ark 密钥供真实推理使用；密钥通过隐藏终端输入或环境变量 `ARK_API_KEY` 提供。每次试跑使用新的目标目录。以下在仓库根目录执行。

```sh
python -m unittest discover -p 'test_s1*.py' -v
COPYFILE_DISABLE=1 tar --format ustar -C s1 -cf - Table.Dockerfile __init__.py game.py table.py | docker build -t longworkmem-table:1 -f Table.Dockerfile -
python -m s1.pilot runs/s1/s1-smoke --backend docker --smoke --limit 30
python -m s1.pilot runs/s1/s1-main --backend docker --seed 31 --limit 150
python -m s1.pilot runs/s1/s1-current --backend docker --control current --seed 31 --limit 30
python -m s1.pilot runs/s1/s1-reminder --backend docker --control reminder --seed 31 --limit 30
python -m s1.grade runs/s1/s1-main/A
python -m s1.grade runs/s1/s1-current/A
python -m s1.review runs/s1/s1-main/A
python -m s1.review runs/s1/s1-main/A --turn 7
```

若 Docker 使用非默认本地 socket，在运行器的环境中设置 `DOCKER_HOST`。镜像仅包含牌桌、模拟器和标准库，启动前按镜像 ID 校验游戏代码。比赛容器断网，根文件系统只读，挂载本场的 SQLite 目录供事务写入。CLI 的上游桥接、凭证、其他赛季、评分器和轨迹都在牌桌之外。开发机也可用 `--backend native` 运行相同 MCP 工具。

八轮的宿主检查包括揭幕站和第二站（7＋8）、邀请赛两小场（7＋8）、回主赛首次真正出牌和全站累计（10＋5）、统一组正式锁定的构筑在两手公开租借牌上能否达到 15 游戏分（30）、自由组两场实际晋级和终局付款（10＋10＋5）。每轮的比赛分是公开游戏规则。宿主检查的各项权重、宿主答案和评分实现不发送给模型。冷启动用全新 Claude 会话和空笔记进入同一报名台，只评统一席位，分母 30。

在每条轨迹中按顺序读 `trace/prompt-N.txt`、`trace/turn-N.jsonl` 和 `trace/tools-N.jsonl`，用 `snapshots/N.json` 核实回复中的完成、得分、付费和报名陈述。`trace/api-*.json` 保存逐次请求与回执。独立复评使用冻结游戏材料和实际动作重放；新版本规则可能拒绝旧快照，复现原发布成绩应使用该次 manifest 标记的代码。输入损坏、快照缺失和成绩为零应分别检查。开发轨迹留在使用者的运行目录，不进入被测环境。

### S1 器材交接和换班记忆

`python -m unittest discover -p 'test_s1_relay*.py' -v` 检查每一档的 A/B、撤回和阶段有效期、部分分、受限交接簿参考解、异常回执和独立重放。在仓库根目录运行以下命令。环境变量 `ARK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_API_KEY` 仅供宿主桥接读取。

```sh
python -m s1.relay_pilot runs/s1/relay-dev --models deepseek qwen --seeds 193 --level 1 --condition relay --direct-response --edition warehouse
python -m s1.relay_review runs/s1/relay-dev/warehouse-L1-193-*
python -m s1.relay_review runs/s1/relay-dev/warehouse-L1-193-* --compare
```

每个赛季目录必须是新的。每轮交叉核对 `trace/prompt-N.txt`、Claude 原始 JSONL、上游请求及返回、`receipt-N.json`。无法独立重放的赛季不参加模型对比。对照条件用 `continuous`、`current` 或 `evidence`。分数以四个阶段的整季百分制汇总，独立样本按种子计数。

### S1 连续跨区长赛季

在仓库根目录运行；双模型沿用器材交接版的宿主环境变量。每次选新输出目录。所有比赛材料和原始提交均按轮冻结。

```sh
python -m unittest s1.tests.test_s1_circuit -v
python -m s1.circuit runs/s1/circuit --desks 10 --qualifiers 2 --level 2 --seeds 2831
python -m s1.circuit_review runs/s1/circuit/Q*
```

`--history regional` 为每区独立保留一个会话，区序和订单与连续条件一致。复评逐轮核对系统提示、用户公文、Claude 会话编号、真实上游回复及配发记录，分别列示实测累计输入、首次提交输入、单次峰值与缓存命中。开发种子及独立验证结果见 `s1/reports/s1-circuit.md`。

正式混合赛的运行参数为 `--desks 10 --qualifiers 2 --level 2`。中途主动整理资料的短对照使用 `--history handover`，在赛季中点由模型用 note 提交最多 5,500 字符的摘要，下一轮新会话只能带入实际留存的摘要。连续主赛没有这个切换。

同场复测 GPT-6.1 Sol 可执行 `python -m s1.circuit runs/s1/gpt-sol --models gpt-6.1-sol --desks 10 --qualifiers 2 --level 2 --seeds 39107 88469`。宿主读取 `OPENAI_BASE_URL` 与 `OPENAI_API_KEY`。该路由最低支持 low 推理档，审计要求实际发送此档位、返回指定模型并能从终端提交重建分数。

长赛季每个模型和种子只运行一次，默认模型为 DeepSeek。每区第 1、2、3、6 班各登记两队的四个字段。开幕后优先抽查本班撤回或批准涉及的队伍，适用范围与截止时点由当班任务指定。四班各占 7.5 分，各区等权。缺字段只失去对应分数，空回复为零，笔记和文字声明不计分。第 4、5、7、8 班分别占 14、10.5、28、17.5 分，照实际回执逐队验收器材及送达。复评报告列出两部分分数；grade.json 保留每区、每班、每队的实际值与期望值。旧 manifest 沿用原公文、原权重。
