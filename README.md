# LongWorkMem-Bench

工作场景长程记忆评测基准。每题是一条连续工作流程，按实际文件、工具回执和环境状态评分。公开协议 `public-v1` 固定 **17217/A**；各模型收到相同的初始材料和业务规则，独立会话保留各自的后续交付。

| Domain | 题目 | 检查什么 |
|---|---|---|
| Work | [W1 · 跨月采购关账与奖金分配](tasks/w1/) | 九轮内冻结六月报送件，处理七月调整，并据先前批复办理工资、资金和预留。 |
| Code | [C1 · 工时结算与保证金交割](tasks/c1/) | 修改同一程序，在第 5、7 轮换班，按轮末交付和新来件复跑评分。 |
| Simulation | [S1 · 跨区器材联赛](tasks/s1/) | 十区八十轮，第 40 轮交接自写摘要；从赛事单据复核登记、器材配套和送达。 |

## 运行与验证

从仓库根目录使用 Python 3.12。每道题的 README 包含 Docker 环境、运行命令和复评入口。模型新作答需要相应推理服务；已有轨迹复评及以下回归测试可离线运行。宿主需有 LibreOffice Calc 完成 W1 工资簿测试。

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r tasks/w1/requirements.txt
python -m unittest discover -v
```

默认无模型请求次数上限。额外试跑预算、W1 的 ERP 限批以及 C1 的提前取件各自单列。材料指纹、评分边界与测量局限见[公开协议](docs/protocol.md)。

## 实测数据

[24 场双模型结果与逐题分差归因](docs/results/advanced-audit-20261127/)给出六组原分、token、每个阶段对均分偏差的贡献及对应实例。该批使用四个配对业务种子与当时的试跑配置。完整轨迹按题归档，公开索引附校验值。[归档约定](rollout/)
