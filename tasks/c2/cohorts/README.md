# C2 · 客户身份迁移与故障续投

在已有 Python/SQLite 日历门户上维护四个客户邮箱、两个业务频道、两门课程和两个服务日。每个业务频道同时有老报名和新订阅；同一客户的两门课也可能属于不同代。四份已登记的旧邀请可在原门户打开。首次建库时先处理的标识，在后续变更、撤回和恢复时仍须指向同一个客户事件。

| 轮次 | 委托与关系 | 独立验收举例 | 分值 |
|---|---|---|---:|
| 1 | 修复旧门户分页 | 4 个区段，分别验 UID 序列与下一游标 | 4 |
| 2 | 导入春季班表、报名与生效附件 | 每个客户两门课的两个业务日分别验时刻、报名编号、结果范围 | 8 |
| 3 | 迁移新订阅身份 | 逐条报名比较含时区的切点；读回旧报名与门户邀请，另从第 2 轮库重放两种切换时点 | 13 |
| 4 | 四端首发 | 实际签收的 UID、时刻、状态及通知次数 | 7 |
| 5 | 客服只读预览 | 同一个答复里的 UID 和伦敦当地时间分别得分 | 4 |
| 6 | 切回发布，临时改时 | 第二周变更事件、未变课程与日期、多发或漏发分开检查 | 10 |
| 7 | 驳回上轮部分批准，暂停发件 | 按其真实前态验每端待发包；只换一份签署附件，重查撤回客户、相邻客户和撤回前版本 | 14 |
| 8 | 队列超时与部分冻结 | A/B 放行，C/D 冻结。已知正确签收与单行过期签收分别测试差量程序 | 10 |
| 9 | 从第七轮磁盘恢复并接管事故 | 收件日志跨恢复保留；核查真实新通知、原键补发，以及仅带源码和备份的冷启动 | 16 |
| 10 | 历史争议 | 40 笔工单逐字段核验；在同一程序上逐次只换一个客户的一条签收，核验应发、实收、未结和邻端 | 14 |

十轮中仅第 5 轮转去客服，随后回到发布主线。独立的只读宿主评分器将上述 100 分展开为 **697 个具名细项**。每项有固定分母、分数、适用轮次、业务键、期望、观测和是否通过。最大单项 1 分。权重使用有理数保存；按字段计分处会区分缺失、合法 null、布尔值和等价的时区表示。故障注入自动签收的 C 项从模型的发布行为中剔除，同键同内容的重试只产生一次签收。

## 工位与启动

复用 C2 固定 Docker 镜像、旧门户、SQLite 库和区域档案。班表指向 104 周档案中的签署续约单，同目录保留一份已过期旧件。每轮只交付当前工单。可读写工位包含 project/data/out/scratch/notes；input 只读。模型通过同一 Claude Code 会话使用 shell、publish 和 receipts。第 9 轮由 Docker 从只读恢复介质重置 data；区域签收日志由宿主维护。客户按 UID 更新邀请，每个新 key 都产生一次实际通知。宿主的参考实现、评分代码及以后的工单不进入参评工位。

从仓库根目录运行。沿用原 C2 的宿主凭据设置与 Docker 共享目录。模型正式运行需要一个尚不存在的 RUN 目录；离线验收无需模型 API。

```sh
python -m pip install -r tasks/w1/requirements.txt -r tasks/c2/requirements.txt
docker build -t longworkmem-calendar:1 -f tasks/c2/Dockerfile tasks/c2
export C2_TEST_ROOT=/path/to/docker-shared/scratch
mkdir -p "$C2_TEST_ROOT"
python -m unittest -v tasks.c2.cohorts.tests.test_cohorts
python -m tasks.c2.cohorts.runner /path/to/shared/new-run
python -m tasks.c2.cohorts.grade /path/to/shared/new-run > grade.json
python -m tasks.c2.evolution.audit /path/to/shared/new-run grade.json
```

协议为 `calendar-cohorts-v2`，评分为 `calendar-cohorts-v2/atoms-1`。通用入口 `tasks.c2.evolution.grade` 也能按运行清单分派评分器。旧版完整成绩在原协议下复现。[工程验收、分项和限制](../../../docs/results/c2-cohorts/)
