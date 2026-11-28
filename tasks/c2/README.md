# C2 · 跨时区排期门户与日历发布

当前版本为[客户身份迁移与故障续投](cohorts/)。十轮前版 [C2 · 排期门户的双版本发布与历史追溯](evolution/) 继承此版上线工位，增加四端、多版本、局部撤回和对账追溯。下文为已归档八轮版本。

在一个连续的 Claude Code 会话中维护旧门户。Python 3.12、SQLite 和固定镜像内的时区库支持文本 HTTP、旧客户端和真实的本地订阅回执。两个频道接收稳定单场 UID 的 iCalendar 2.0 事件。每次 shell 调用在新的无外网容器中运行，工位持久化。宿主维护订阅端、控制业务时钟和故障顺序，评测代码与未来签批位于工位之外。

| 轮次 | 工作 | 当轮分值 |
|---|---|---:|
| 1 | 修复跨日列表、旧邀请和 UTC API | 9 |
| 2 | 迁移既有报名，按两份签批递推当地钟点或 UTC，接受新系列 | 21 |
| 3 | 只读伦敦预览 | 4 |
| 4 | 两频道正式首发，验证实际订阅与可复跑导出 | 8 |
| 5 | 单场改期和两周临时窗口，增量同步 | 16 |
| 6 | 仅撤回 B 频道第二周批准，保留其他变更 | 14 |
| 7 | 收件后丢回执、收件前断线，核查、补发、复跑 | 16 |
| 8 | 备份恢复，发布第二季度并支持新订阅者 | 12 |

资料库含 96 份已到期工单、96 份场馆资料、96 份关联日志表（9,984 行历史投递）。试点处于同一纽约时间和 UTC 时刻开始；越过夏令时后才显现不同合同效果。发布服务按频道独立接收、按 key 幂等。第七轮可查对双方真实收件记录。验收按实际前态核对变更范围，隔离副本重启 HTTP 服务、增量迁移、导出、新来件恢复和只带源码及备份的冷启动。ICS 由独立解析器比较 UID、绝对时刻和业务状态。

从仓库根目录运行。宿主需有 Python 3.12、Claude Code、Docker；凭据仅由宿主读取。Docker VM 须将正式运行目录和 C2_TEST_ROOT 置于可读写共享挂载。准备一个新目录名用于每次正式作答。

```sh
python -m pip install -r tasks/c2/requirements.txt
docker build -t longworkmem-calendar:1 -f tasks/c2/Dockerfile tasks/c2
C2_TEST_ROOT=/path/to/shared/tmp python -m unittest discover -s tasks/c2/tests -t . -v
python -m tasks.c2.pilot /path/to/shared/run
python -m tasks.c2.grade /path/to/shared/run
python -m tasks.c2.audit /path/to/shared/run
```

正式入口从 ARK_API_KEY 读取凭据，使用 deepseek-v4-1-flash-261017。同一次会话完成八轮、按轮签收，无模型请求次数上限。末两条命令只复评既有交付并核查轨迹，无需模型接口。测试构建使用宿主参考实现；模型工位只接收 starter 下的应用文件和当期业务材料。

换签批配对诊断可使用 `python -m tasks.c2.dependency RUN`。从第 2 轮冻结交付创建两份副本，复用相同的新系列，只交换签批引用，核对跨夏令时的两个目标场次。该诊断单列。[首轮实测与审计](../../docs/results/c2-calendar-20261128/) · [轨迹](../../rollout/c2/)

## calendar-v1 题面勘误与适用范围

- R4 中的频道清单指委托指定的 A、B 两个频道，两者首发均含两个试点；本版没有另附频道清单文件。
- R8 明确检验指定日期范围、旧链接和冷启动的订阅结果。无参页面的默认展示跨度、超过千场的单请求分页策略未纳入这版验收。
- 宿主订阅端的重复通知按真实接收批次计算。仅为检查而重试同一 key、内容语义相同且返回 already_received 的情况不会再通知用户。

跨机复评默认核用场次清单记录的镜像。若本机只有按同一 Dockerfile 重建的镜像，可显式传 `--image longworkmem-calendar:1`；评分回执记录实际 replay_image。
