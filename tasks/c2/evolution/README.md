# C2 · 排期门户的双版本发布与历史追溯

接手一个已上线的 Python/SQLite 排期门户。旧客户端与客户报名仍在使用；新产品线要同时服务四个订阅端。十轮使用同一个 Claude Code 会话、同一份源码和数据库。发布会实际更新可查询的订阅端。客户最后追问某个历史版本时，工程师须分别重建当时的应发状态和实收状态。

## 工位与交互

| 位置或工具 | 模型可执行的工作 |
|---|---|
| project、data | 阅读和修改旧门户、迁移数据、起本地 HTTP 服务、运行旧客户端与回归套件。工位继承上一次日历发布的真实代码、SQLite 数据和交接件。 |
| input | 只读。含旧业务档案、新批复、身份映射、客服来件及区域历史。区域档案覆盖 104 周、6,656 条事件、26,624 条渠道投递行。新合同与工单按轮到达。 |
| out、notes、scratch | 构建 ICS、发布包和备份，可持久保存工程笔记、测试与索引。旧发布产物位于 input/previous-release/out。 |
| shell | 在无外网的 CPU Docker 容器中运行命令，跨调用保留工位文件。HTTP 可在同一命令内通过回环访问。 |
| publish、receipts | 向指定端真实提交 ICS，按 key 和事件语义幂等；查询实际在线批次。第五轮起早期回执进入只读归档。 |

模型仅获得当轮委托、公开接口、当时的工位和工具。宿主单独保存后续工单、评分程序、参考实现、冻结快照与完整订阅日志。场次结束后在每轮快照的副本上评分。

## 会话与检查点

| 轮次 | 工作 | 新版主要验收 | 原分值 | 新分值 |
|---|---|---|---:|---:|
| 1 | 旧门户分页 | 深页、尾页与旧链接可用；分页成功时再计兼容 | 6 | 4 |
| 2 | 排期内核 | 常规配置少量计分，重送、优先级、限域撤回用新系列检验 | 16 | 10 |
| 3 | 双版本迁移 | 同一程序集成 V2 和 ICS；宿主从第 2 轮库迁移，临时改一端的映射，检查旧事件、旧报名和刚登记的报名 | 4 | 8 |
| 4 | 四端首发 | 真实签收，重复通知折损 | 6 | 3 |
| 5 | 客服预览 | 当轮产物和可复用入口各 1 分，保留只读条件 | 2 | 2 |
| 6 | 临时批复 | 核对变化行和导出，按正确投递、漏投、多投给部分分 | 14 | 13 |
| 7 | 局部撤回 | 同一批复仅对指定端和日期失效。空计划 A 占 1 分，B/C/D 实际回退各 3 分；提前发送损失对应频道分 | 8 | 10 |
| 8 | 事故恢复 | 分离环境已签收项目、原键补发与重复通知，复跑换一份实收状态 | 14 | 16 |
| 9 | 冷启动交接 | 源码及备份恢复后的发件与历史查询；两份干净副本重送同一张限域撤回，只交换适用频道，检验新版本与旧版本 | 14 | 16 |
| 10 | 客服追溯 | 核对应发、实收、未结；每次仅改变一端的一条历史签收，受影响的答案须改变，邻端须保持 | 16 | 18 |

总分 100。新场在 manifest 标记 `calendar-evolution-v1/cases-1`，宿主执行 70 项计分。本次校准沿用现有十轮题面及参评工具；原场仍按其当时可见的字段约定复评。新的业务输入仅在提交后的沙箱副本中出现。稳健性、计分口径、逐项实得及局限见[校准报告](../../../docs/results/c2-case-calibration/)。

## 运行及离线复评

从仓库根目录运行。Docker 镜像与 C2 旧版相同；正式场使用新的共享目录及宿主环境变量 ARK_API_KEY。固定业务实例为 17217/A，模型请求无题目上限。环境只向模型开放上述三种工具。

```sh
python -m pip install -r tasks/w1/requirements.txt -r tasks/c2/requirements.txt
docker build -t longworkmem-calendar:1 -f tasks/c2/Dockerfile tasks/c2
export C2_TEST_ROOT=/path/to/docker-shared/scratch
mkdir -p "$C2_TEST_ROOT"
python -m unittest -v tasks.c2.evolution.tests.test_evolution
python -m tasks.c2.evolution.runner /path/to/docker-shared/new-run
python -m tasks.c2.evolution.grade /path/to/docker-shared/new-run > grade.json
python -m tasks.c2.evolution.audit /path/to/docker-shared/new-run grade.json
```

离线复评只需 manifest、snapshots 和 receipts。完整轨迹审计还需要原始 CLI、MCP、供应商请求和响应。初始客户端和归档来源固定，历史测试有各自的输入与产物前提。还原原交付可在隔离副本中把 input/previous-release/out 的文件复制到 out 后运行旧测试。

跨机复核可在 grade 后加 `--image longworkmem-calendar:1`，应与原固定 Dockerfile 一致。输出含实际镜像标识。单独运行 `python -m tasks.c2.evolution.dependency RUN` 可复核第十轮程序是否随历史回执改变答案。此项配对诊断单列。

[首场 10 轮盲测审计与逐项回放](../../../docs/results/c2-evolution-20261128/)使用冻结提交 aa837f9 的原始题面。当前开发版增加合同文件索引和 day 的业务定义，运行清单另记 material_revision，供后续配对比较。

已归档场次沿用原评分版本。要在历史工位上显式复算新版分数，运行 `python -m tasks.c2.evolution.case_grade RUN`。
