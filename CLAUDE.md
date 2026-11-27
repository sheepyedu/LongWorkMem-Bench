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

## 目录与运行回执

三题各自使用根目录 w1/、c1/、s1/，保留原 Python 模块入口。每题 README.md 导航，TEST.md 保存从仓库根运行的命令，tests/ 存放可发现的回归测试，reports/ 存放题目报告。跨题共用的 Claude 适配器和宿主网关沿用 w1 的模块路径。
正式轨迹按 rollout/<题号>/<批次>/<run-id>/ 本地保存。公开仓库保留题目、工具、说明及脱敏审计。原始轨迹、宿主评分器及凭据均位于被测工作区之外。

## 正式题目

public-v1 三题共用 benchmark_protocol.py 的种子 17217 和版本 A，重复实验新开独立会话。改变材料须更新协议及公开指纹。默认无模型请求次数上限；额外试跑额度与效果分开记录。
- W1 九轮按轮末产物和真实邮件评分。ERP 窗口是显式选择的历史对照。
- C1 保留第五、第七轮换班及暂时可阅的签发通知。轮末交付是公开主条件，提前签收只用于对照。
- S1 业务引擎在无网络 Docker 容器运行；公开十区八十轮，中段换班仅传代理 note。按 manifest 版本重放已有记录。
