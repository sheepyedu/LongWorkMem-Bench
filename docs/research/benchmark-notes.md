# 超长工作会话评测的构造依据

2026 年 11 月 24 日 · 立项研究笔记。后续新增基准及样题设计见[三类九题讨论稿](../design/session-candidates.md)。

**立项判断。** 现有工作分别证明了三件事可以被测量：信息经过一次上下文变更后能否取回，跨应用操作能否产生正确的业务状态，同一项目持续演进时旧能力能否保住。我们的独立问题在三者的交点：**一条真实工作主线中，早先的有效信息会不会改变数轮之后的交付，以及模型为取得这个结果花了多少成本。** 一道候选题应能指出哪条早期事实、哪一次后续决策、哪个产物字段构成这一关系。

## 1. CLM 和 ContextBench 如何把“上下文管理”单独测出来

CLM 把本轮活跃上下文镜像成文件。模型可以用 Bash 改写、摘取或移出内容，运行框架将改后的表示同步为后续生成的输入。普通工作文件也能帮助记忆，区别在于写一份笔记本身没有改变活跃上下文。论文另做了技能提示优化和权重训练。训练中的效率奖励只在同组成功轨迹间比较利用前缀缓存后的估算计算量，组内成功样本不足两个时，这项优势为零。作者还在终端开发、网页检索、长时优化任务中按任务本身的目标评估，让节省计算与工作质量可以同时观察。[CLM §3–5、附录 C–E](https://arxiv.org/html/2609.37725v1) · [官方接入代码](https://github.com/facebookresearch/context-language-models/tree/3c89408be/clm/clm_contextbench)

配套 ContextBench 的四类题有意简化领域推理。Needle Retention 看最终上下文中是否逐字保住指定行。Sudoku Sketchpad 在连续落子后核对 16×16 棋盘各版本。KV Store 要查回早先写入的值。Log Triage 要对流入的服务日志做精确查找或计数。这四种题需要的证据时点不同：允许把键值移出再取回时，只检查最终上下文会漏掉曾在正确时刻交付的答案。环境把每次操作作为同一会话的一条新用户消息送入；在论文设置中，代理准备好后释放下一项。方法专用技能提示也是实验条件，应随配置公开。[论文附录 D](https://arxiv.org/html/2609.37725v1#A4) · [ContextBench 数据与评分器](https://github.com/RulinShao/ContextBench/tree/fb533c18c78a82d3f1b2047a9c1700735cf829ae)

**查到具体实例。** `kv-store-R1000-seed42` 有 10 批、每批 100 个 SET，之后有 24 个 GET，共 34 次输入。公开可行性回执记录累计输入 49,676 token，窗口 32,768，单项最大 4,924，估算需常驻的信息 1,688。这里 1.52 倍表示输入流与窗口之比。项目组可以独立检查“一直保留原文会遇到压力”与“合理整理后仍有可行解”这两个条件。本次从输入流重建键值并调用公开 KV 评分器，全答得到 24/24，省去一条得到 23/24。此次走 `final_report` 回退路径，只检查评分器对答案的反应。公开移植版本还支持逐轮快照和轨迹，评分器容许正确值嵌在较长答案中。[样本与回执](https://github.com/RulinShao/ContextBench/tree/fb533c18c78a82d3f1b2047a9c1700735cf829ae/tasks/kv-store-R1000-seed42) · [KV 评分实现](https://github.com/RulinShao/ContextBench/blob/fb533c18c78a82d3f1b2047a9c1700735cf829ae/contextbench/graders/kv.py) · [公开版差异](https://github.com/RulinShao/ContextBench/blob/fb533c18c78a82d3f1b2047a9c1700735cf829ae/docs/DEVIATIONS.md)

**迁移到本项目。** 保留“输入逐次到达、必要信息量可容纳、按使用时点核验”三个条件。压力来源换成真实文件审阅、工具反馈、需求修订和待办累积。受提醒进行的整理与自主整理分组，普通工作笔记、主动编辑、框架自动压缩分别记录。

## 2. 三种办公评测各自在验证什么

### WorkBuddy Bench 从业务材料与制品入手

Office v1.0 含 50 个任务。抽读的采购对账题随包提供订单与入库两个 CSV，要求产出含五个工作表的 xlsx。题面公开关联键、字段映射与金额容差。程序评分从工作簿中识别类别，按类别核对异常 ID 数、抽查 ID 并检查正常订单误报；另有针对跨表一致性、汇总口径等的模型评委 rubric。题面、参考数据、程序断言、语义 rubric 是四层可分别检查的材料。[官方数据说明](https://github.com/Tencent/workbuddy-bench/blob/625b22330/datasets/README.md) · [Office 发布包](https://huggingface.co/datasets/tencent/workbuddy-bench/tree/main)

**原始数据复算发现一个会影响评分的口径差异。** 对 `procurement-reconcile-L3-015` 的 300 张订单、285 条入库记录，依题面分别比较数量与金额，数量差异 15、金额差异 25、未入库 20、无对应订单入库 5。15 张数量差异订单全都同时有金额差异。参考答案的 10 张金额差异恰等于剔除这 15 张后的集合，评分器在金额表的 ID 数量检查中要求等于 10。例如 `PO-2026-10607` 的数量为 344 对 362，金额为 28,025.68 对 29,492.14。题面明确要求已识别差异的订单不得计入“未入库”，没有明示数量差异优先于金额差异。两张异常表能否重叠，会改变一份按规则认真完成的工作簿能否得分。这个发现限于该版本该题。随附脚本直接读取发布包，采用十进制定点数比较并输出差集。[复算脚本](../../scripts/recheck_procurement.py) · [复算说明与记录](workbuddy-reproduction.md)

### WorkBench 从确定的环境状态反推任务

作者手写 69 个操作模板，基于五个模拟业务数据库实例化成 690 道题。数据记录同时保留用户指令、参考操作、模板和涉及的应用。v1 跨域 CSV 有 210 行。第一题要求在过去两周未联系某客户的条件下，与其 CRM 负责人预约次日最早空闲的半小时。参考动作已经解析出负责人以及 2023-12-01 13:00。被测代理需要自己从 CRM 和日历取得这两个值。同一模板也可产生无需写入的结果。这样设计，可以稳定构造条件分支和应保持原状的对象。[论文 §3、附录 A](https://arxiv.org/html/2405.00823v2) · [v1 跨域样本](https://github.com/olly-styles/WorkBench/blob/49c7dfd00/data/processed/tasks_and_outcomes/v1/multi_domain_tasks_and_outcomes.csv)

论文以数据库最终状态为标准。当前公开代码里的 `is_correct` 会执行并规范化候选动作及参考动作，再逐表比较；还有独立的副作用指标。一次搜索走错又改正，如果留下了正确状态，仍有机会达标。跨轮工作流可把这个思想推进一步：对不可替代的时点冻结状态。草稿可以改，若用户要求仅保存草稿，历史上已经发出的通知则要查投递事件，不能只看最后是否还有草稿。[评分实现](https://github.com/olly-styles/WorkBench/blob/49c7dfd00/src/evals/evaluation.py)

### OdysseyBench 从多日对话恢复跨应用意图

OdysseyBench+ 从已有 OfficeBench 任务生成简短意图和支撑它的多日对话，生成器按验证器反馈修订。Neo 则先探索应用与文件环境，形成可执行的任务、子任务和评分条件，再据此生成多日对话。两部分分别为 300 和 302 题。论文明确说明：生成历史时，历史助手的执行经过文字模拟。被测助手随后从历史和当前请求恢复意图，在环境中工作，最后冻结文件系统；任务要求全部条件成立。设计者可学习它怎样让用户最后只说一句自然的请求，同时要区分历史助手声称完成的事和本次会话真正生成的产物。[论文 §3.1–3.2](https://arxiv.org/html/2508.09124v1)

Neo 的 `tasks/3-97/subtasks_neo/0.json` 把用户的周计划拆成 Excel 时间表和 Word 摘要。数据将面向代理的一句话、完整任务、应保留的事实、检查器参数分别存放。四个检查项分别确认两个文件存在、两个文件含各自关键词。本次直接调用源代码的文字包含函数，只提供各自的关键词串，两项内容谓词均返回真，串中没有任何时间槽。此处只运行了文本谓词，未执行完整容器。对我们的题，适合追加“周三实际时间槽与摘要一致”“调整周三后其余日期保持原样”这类跨制品断言。[真实样本](https://github.com/microsoft/OdysseyBench/blob/3389881fa/tasks/3-97/subtasks_neo/0.json) · [同题分日对话](https://github.com/microsoft/OdysseyBench/blob/3389881fa/tasks/3-97/chat_histories_neo/0_day_session.json) · [评分实现](https://github.com/microsoft/OdysseyBench/blob/3389881fa/utils/evaluate.py)

## 3. 怎样构造持续推进的主线，又怎样证明推进发生过

**SWE-Milestone。** DeepCommit 从两个发布版本之间的实际提交出发，结合提交说明、issue/PR、逐行依赖、符号变化和文件共同修改聚合里程碑。先选功能主题，再归并提交、推断依赖、拆解过大的节点，最后用构建与测试检验依赖图。代理在持久代码库中按解锁顺序实现，阶段提交被冻结后独立评分。论文分别计入新增要求的完成和原有测试的回归，并按演进区间宏平均。其 Recall 对应待实现功能，Precision 衡量改动中修复与破坏的关系，不能将 Precision 解读成“旧测试通过率”。[论文 §3–5](https://arxiv.org/html/2603.13428v4) · [官方评测仓库](https://github.com/DeepCommit-ai/SWE-Milestone/tree/17a8f1593)

Navidrome 的 v0.57.0→v0.58.0 数据给了一个可移植的真依赖：多媒体库支持先有数据库结构与持久化，再做核心服务及扫描器，再接服务端 API，最后接 UI。依赖表将这条链接到 `milestone_003_sub-01 → sub-02 → sub-03 → sub-04`，并附每条边的理由。把这种证据移到办公题，就是先有核准行项目，再有分配明细，再有从明细生成的汇总；只改一条获批记录，应能预测哪些下游数字变化。此前本项目在同一冻结提交上更换评分工作树清理方式，定向复评出现分数变化。这要求试跑以干净快照验证删除和重命名都能传到评分环境。[官方数据](https://huggingface.co/datasets/DeepCommit-ai/SWE-Milestone-data) · [五仓审计摘要](prior-observations.md#swe-milestone)

**LHTB。** 论文 v3 的 46 题从专业工作流出发，提供可运行但有缺陷的初始项目、公开材料、标准解与私有验证器，用校准运行筛题。多数分数来自可复现的中间目标和隐藏条件。值得注意的是，论文主要从**运行结束时的容器状态**计算子项分数。这能确认最后留下了多少有效工作，却不能证明中断发生前已做到哪一步。本项目若要测切回后的恢复，必须在切走前和返回后分别取证。[论文 §2.1–2.4](https://arxiv.org/html/2607.08964v3)

原始任务 `document-table-layout-reconstruction` 交付带位置噪声的 OCR、扫描页和元数据。初始实现相信错误的 token 顺序，修复后的 CLI 应产出 CSV、JSON、Markdown 和质检记录。其评分代码把 **0.890** 权重给隐藏场景端到端压力测试，CLI/schema、公开样例 sanity、公开重建各占 **0.005**。公开文件齐全并不能证明能处理打乱的 OCR。发布仓库 2.0 另列 31 道新题，合计 77 题；新题中的 LiDAR 重建样本使用六级连续门槛，覆盖存在可编辑工件、隐藏输入可运行、输出会随输入变化、语义正确等。原论文、扩展任务和本项目阶段审计各自有不同分母。[原题与评分代码](https://github.com/zli12321/LHTB/tree/7ca0cacea9bf6a0694eaad7306bed794eaaaabce/tasks/document-table-layout-reconstruction) · [2.0 重建样本](https://github.com/zli12321/LHTB/tree/7ca0cacea9bf6a0694eaad7306bed794eaaaabce/tasks-2.0/lidar_icp_registration_summary__06)

**CTXAgent。** 作者将编程练习和相互调用的 SciCode 步骤编成可回放会话，另植入三种可核验依赖：用户陈述的事实、从随后删除的文件里看过的临时值，以及后续持续生效的回复规则。设置多个来源到使用的轮距；同一依赖是否跨压缩，是根据实际请求事后标注。论文使用相邻请求长度同时下降超过 25% 和 10k token 的启发式估计，所以它与 Harness 明确发出的压缩事件应分列。短的 clean chains 在无额外干扰时测同类步骤能做到什么程度；正面运行中，隔开的编程任务既是工作量，也会带入有用工具结果。[论文 §3.2–3.5](https://arxiv.org/html/2610.34425v1#S3.SS3) · [组题代码](https://github.com/MatthiasHBusch/CTXAgent/blob/7fc376ce1/bench/tasks_mix.py)

公开结果 `p2_mixdep.jsonl` 首行是一条 101 轮的 Claude Code 会话：10 个事实探针与 10 个临时观察探针各自全对，59 个 question 类轮次得分均值约 0.949。这行说明，一段会话可以在直接回忆上满分，业务类任务仍有失败。它不能单独证明那几道题因上下文而失败。我们的主探针应落到后续工作必须提交的内容上，并标注是否允许从业务系统重新取得证据。[原始结果行](https://github.com/MatthiasHBusch/CTXAgent/blob/7fc376ce1/bench/results/p2_mixdep.jsonl) · [依赖组装](https://github.com/MatthiasHBusch/CTXAgent/blob/7fc376ce1/bench/seqdep.py)

## 4. 已有自有实验约束了怎样的解释

本项目 LHTB 五题两组共十条线次，阶段审计记录原生组 30 次自动压缩，CLM 组 23 次，未记录被接受的自主 CLM 编辑。SWE-M 五仓对照中，原生组和每请求提醒组分别为 8,085 与 4,815 次完整请求；平均输入 78,545 与 79,074，未命中输入总量 17.77M 与 27.51M，沿用原审计价表估算约 ¥47.32 与 ¥47.00。两项观察分别支持“编辑能力与实际使用分开统计”和“成本按请求、缓存与输出拆账”。它们均未隔离某一次编辑的因果作用。[LHTB 阶段观测汇总](prior-observations.md#lhtb) · [SWE-M 四组审计摘要](prior-observations.md#swe-milestone)

**对立项的直接约束。** 每条主依赖交付三份东西：决策来自何处、它改变了哪个后续产物、只改变这条决策的另一版本预期如何变化。每个检查器同时有参考解、合理的不同实现和“表面正确但业务关系错”的失败样本。这样可以先检验题目有没有测量能力，再用真实模型估计不同策略带来的质量与成本差异。当前样题和试跑判据见[三类九题讨论稿](../design/session-candidates.md)。最早的试跑合同见[历史设计 v0.1](../archive/pilot-v0.1.md)。
