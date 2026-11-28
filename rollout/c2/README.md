# C2 轨迹

| Claude Code + DeepSeek 4.1 Flash | 记录 |
|---|---|
| [客户迁移版正式场](deepseek-v4.1-flash/cohorts-17217-A/) | 93.60/100；十轮、697 个细项、真实签收、公开轨迹与可复评分包。 |
| [十轮进阶版正式场](deepseek-v4.1-flash/evolution-17217-A/) | 367 个请求、403 次工具交互、十个冻结工位及四端真实签收。使用 tasks.c2.evolution.grade 复评。 |
| [修正接口后的正式场](deepseek-v4.1-flash/official/) | 八轮题面、模型可见回答和工具往返、逐请求用量、评分与冻结业务交付 |
| [保留的环境诊断场](deepseek-v4.1-flash/diagnostic/) | 含回执工具参数不一致及原始错误 |

GitHub 版省略供应商推理正文、宿主路径和账户遥测。实验机另存完整原始请求与响应、CLI 转录和工具日志。每场先校验 SHA256SUMS，再复制目录到临时位置解包 artifacts.tar.gz，即可使用 C2 评分器离线复核。复评运行环境见[题目说明](../../tasks/c2/)。
