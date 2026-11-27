# 进阶版运行与验收

从仓库根目录运行，使用 Python 3.12、Claude Code CLI。W1、C1 需要 Docker 和可读写的共享工作目录。W1 宿主复算另需 LibreOffice Calc。S1 使用纯文本动作与宿主赛事引擎。

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r w1/requirements.txt
python -m unittest discover -v
```

| 题目 | 运行与复评 | 完整一场的边界 |
|---|---|---|
| W1 | [运行手册](w1/TEST.md) | 九轮，九份阶段快照，一套实际投递记录 |
| C1 | [运行手册](c1/TEST.md) | 七轮，同一工作卷，两次已通知的人员换班，取件与修复分别计分 |
| S1 | [运行手册](s1/TEST.md) | 十区八班交错发布，共八十轮，在每轮原始回答上重放登记与订单 |

每次指定全新的输出目录。使用两个模型比较时逐场固定种子、业务版本、任务配置和预算。记录实际请求、缓存和异常重试，核对模型回复、工具回执与冻结的交付。
