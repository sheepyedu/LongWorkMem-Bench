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

| 轮次 | 关系 | 工程交付与可观察行为 | 分值 |
|---|---|---|---:|
| 1 | 主线 | 修复老接口千场截断，分页游标、尾页、旧邀请和旧 API 可复用 | 6 |
| 2 | 主线 | 在旧库上增量登记可重送、乱序到达的批复。更换系列、优先级和撤回范围后仍按已知版本查询 | 16 |
| 3 | 主线 | 同一业务场次接通 HTTP V2 与四端 ICS，各端使用登记的线协议 UID | 4 |
| 4 | 主线 | 四端三月首发，按真实签收行验收，重复通知影响得分 | 6 |
| 5 | 半相关 | 转入客服只读预览，复用排期内核，处理另一组预览；不发送通知 | 2 |
| 6 | 切回主线 | 实现临时窗口、单场提前和多频道覆盖。分别验证变更行、全量导出与实际最小投递 | 14 |
| 7 | 局部驳回 | 上轮批准只撤回指定端及日期。对各端的真实前态生成待发包，核查未提前发送 | 8 |
| 8 | 事故恢复 | 两项超时分别发生在收件前后。核对归档和在线回执，按原键补缺，换一组实收状态再次检查差量程序 | 14 |
| 9 | 阶段转换 | 从源码及数据库备份冷启动，跨新一轮夏令时切换交付秋季排期，保留早期修订与旧邀请 | 14 |
| 10 | 客服追溯 | 提供可重复调用的查询程序。按历史版本输出应发、实收、是否未结；另给不同客户问题和不同签收史 | 16 |

总分 100，72 个带权检查项。集合按 UID、业务键或问题键对齐，时间归一到 UTC。每行同时考虑漏项和多余项；独立计分的交付项、状态项和副作用项见宿主评分程序。新接入业务、订阅实收、回退和历史追溯共同构成跨轮依赖。模型声明“完成”、笔记长度、请求数和压缩次数均不计任务分。

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
