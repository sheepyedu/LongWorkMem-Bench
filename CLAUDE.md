# LongWorkMem-Bench — 项目指南

> **重要：Claude 必须自主维护本文件。** 架构或约定变化时更新，保持简洁。

## Git 信息

- Remote: https://github.com/sheepyedu/LongWorkMem-Bench
- 默认分支: main

## 任务生命周期

你收到任务后，按以下 9 步流程自主完成：

1. **领取任务** — 你已被分配任务，阅读本文件和项目代码理解上下文
2. **创建工作区**:
   - `git fetch origin`（如有 remote）
   - 远端已有 `origin/main` 时从它创建 worktree；首次发布前从本地 `main` 创建
   - 进入 worktree 目录工作（后续所有操作在 worktree 中）
   - 如果 worktree 创建失败，直接在当前分支工作
3. **实现功能** — 编写代码，确保可运行
4. **提交代码** — `git add` + `git commit`，commit message 简洁描述改动
5. **Merge + 测试**:
   - `git fetch origin` 后仅在远端分支存在时合并 `origin/main`
   - 运行测试（如有测试命令）
6. **自动合并到 main**（如有 remote）:
   - `git fetch origin` 后若远端分支存在，则 `git rebase origin/main` 并处理冲突
   - 若 `git ls-remote --refs origin` 成功且没有任何 refs，则以本地初始提交为基线，普通 push 创建远端分支
   - 如果成功：`git checkout main && git merge <task-branch> && git push origin main`
   - 如果这一步有任何失败，退回到步骤 5 重试
   - （纯本地项目跳过本步）
7. **标记完成** — 更新文档（必须在清理之前，防止进程被杀时状态丢失）
8. **清理** — 回到项目根目录:
   - `git worktree remove .claude-manager/worktrees/<worktree名>`
   - `git branch -D <task-branch>`
   - 如有 remote: `git push origin --delete <task-branch>`
9. **经验沉淀** — 在 PROGRESS.md 记录经验教训（可选）

### 冲突处理

rebase 发生冲突时：
1. 查看冲突文件: `git diff --name-only --diff-filter=U`
2. 逐个解决冲突
3. `git add <resolved-files> && git rebase --continue`
4. 如果无法解决: `git rebase --abort`，退回步骤 5

### 状态判断

- 通过 `git remote -v` 判断是否有 remote
- 有 remote → 必须完成步骤 6（merge + push）
- 无 remote → 跳过步骤 5 的 fetch、步骤 6 和步骤 8 的远程分支删除

## 文件维护规则

> **以下文件都由 Claude Code 自主维护，每次功能变更后必须同步更新。**

- **CLAUDE.md**（本文件）：架构、约定、关键路径变化时更新，只改变化的部分，保持简洁
- **AGENTS.md**（Codex 读取）：**与 CLAUDE.md 保持关键内容同步**——这是 CC/Codex coding 时的行为纪律：往其中一个写新内容时，把相同的意思也写进另一个（不要求逐字一致）。正常状态它是指向本文件的 symlink（改一处即同步），不要改成独立文件；若两者已是独立文件，不要用 symlink 覆盖已有内容，逐次同步意思即可
- **README.md**：面向用户的文档，功能、使用流程变化时同步更新，保持与实际代码一致
- **TEST.md**：测试指南，新增功能时同步添加测试用例和文档
- **PROGRESS.md**：见下方「经验教训沉淀」

## 测试规范

**开发时必须主动使用测试，不是事后补充！**

- **改代码前**：先跑测试，确认基线全绿
- **改代码后**：再跑一遍确认无回归
- **新增功能**：同步新增测试用例，更新 TEST.md
- **修 bug**：先写复现 bug 的测试（红），修复后确认变绿

## 经验教训沉淀

每次遇到问题或完成重要改动后，要在 PROGRESS.md 中记录：
- 遇到了什么问题
- 如何解决的
- 以后如何避免
- **必须附上 git commit ID**

**同样的问题不要犯两次！**

## 注意事项

- 在 worktree 中工作时，不要切换到其他分支
- 完成任务后确保代码可运行、测试通过

## W1 开发题

- `w1/world.py` 分九轮发布办公材料，A/B 只改变人事批复的生效月。公开材料中的业务要求与宿主评分说明分开维护。
- `w1/pilot.py` 启动独立 Claude Code 会话。`w1/office.py` 是被测代理的唯一工具入口，只开放共享盘、邮件草稿和投递。`w1/runstate.py` 保存阶段快照。
- `w1/grade.py` 只在宿主按当轮快照和投递时的附件评分。首轮交付与六月补件分别取证，第七轮和最终归档的公式都用独立副本实际改值重算。原始轨迹、评分器、参考解、另一版本材料和上游凭证不进入办公室。变更计分时补正负对照，复评既有快照并保留原成绩。
- W1 进阶题由 `w1/advanced.py` 按级别、种子和人事变体发布，一至六级的采购、薪酬、资金交接分别占 40、35、25 分。七、八级用 30/25/20 加 25 分跨轮预留授权，按办理日逐案取证。旧题继续用级别 0。双模型比较经 `w1/paired.py` 核对逐轮材料摘要、镜像、预算及真实回执，调题和验证分开统计。
- 同种子 A/B 的授权记忆诊断检查须分叉和应保持的案件。`w1/memory_control.py` 用相同现场的新会话比较有无先前主管原话，短对照单列。

## S1 开发题

- `s1/game.py` 维护八轮赛事状态与面向玩家的规则。A/B 只改变开幕侦察的决赛屏蔽类别。公开规则和工具回执不能包含宿主评分项、权重、变体标签或未来牌序。
- `s1/pilot.py` 通过 Claude Code 连续会话操作 `s1/table.py` 的 observe 和 act；Docker 牌桌只挂载本场数据库，逐次轨迹和轮末快照保存在宿主。报名冷启动对照独立开局。
- `s1/grade.py` 重放已接受的动作，以实际出牌、锁定和支付分别计分。`s1/review.py` 核对上游、Claude 和牌桌回执。规则变化后重跑 A/B、等价构筑、单点失误和异常证据测试。

## C1 开发题

- `c1/world.py` 逐轮发放维护委托和来件，两版只翻转第三轮纪要的一句话。`c1/sandbox.py` 仅公开工作区 shell；源码、业务库和笔记跨轮保留。进程中断由宿主调度，立即冻结数据和回执，再向代理交接。
- `c1/grade.py` 从当轮冻结副本运行候选 CLI，按独立事件账核验现态、审计、历史与灾备重建。`c1/review.py` 对齐上游请求、Claude 调用和宿主命令日记。参考实现、评分与另一版保持在被测工作区之外。

- C1 六轮工时结算由 `c1/settlement.py` 分批发布。签收配置在公开的 shell 调用次数处冻结交付，R2 后撤回签发人通知。宿主 `c1/settlement_grade.py` 逐轮比对三站水位、事件、工时和成本，并在新来件上调用交付程序。评分、其他变体与独立参考程序均不进入会话。
