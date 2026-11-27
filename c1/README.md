# C1 · 多来源工单事件库

十二轮工单维护使用真实 Python 源码和 SQLite 存量库。工时结算是独立扩展，按运行模式及对应评分器复评。

| 入口 | 用途 |
|---|---|
| [运行手册](TEST.md) | 从仓库根运行 `python -m c1.pilot --help`；依版本选择手册中匹配的评分命令。 |
| [自动化测试](tests/) | `python -m unittest discover -s c1/tests -t . -v` |
| [正式 rollout 预留目录](../rollout/c1/README.md) | 后续正式运行的目录约定 |

[工单难度校准](reports/c1-calibration.md) · [工单主线试跑报告](reports/c1-pilot.md) · [工时结算校准](reports/c1-settlement-calibration.md)

[历史 A 版逐轮审阅](reports/c1-rollout-a.md)

[历史 B 版逐轮审阅](reports/c1-rollout-b.md)
