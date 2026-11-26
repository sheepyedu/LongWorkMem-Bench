# WorkBuddy 采购对账样例复算

本文核查 Office v1.0 中的 `procurement-reconcile-L3-015`。脚本仅读取压缩包中的两份 CSV 和随包的参考 JSON，按题面独立计算结果。数据包由上游作者发布。[官方数据入口](https://huggingface.co/datasets/tencent/workbuddy-bench/tree/main) · [上游数据说明](https://github.com/Tencent/workbuddy-bench/blob/625b22330/datasets/README.md)

## 操作

在仓库根目录，先从上游数据入口取得 `wb-bench-office-v1.0.tar.gz`。用 Python 3 运行下列命令，以实际下载位置替换参数。

```sh
python3 scripts/recheck_procurement.py /path/to/wb-bench-office-v1.0.tar.gz > result.json
diff -u docs/research/evidence/workbuddy-procurement.json result.json
```

无须安装额外依赖。脚本使用订单号作为关联键，按入库单号最后的序号拆出订单号，将属于同一订单的入库金额与数量分别求和，金额差绝对值大于 0.01 元时计为有差。本次读取的数据包 SHA-256 为 `89d4480b483ca2e0555ba96cc7d73c16c78802b17cd822044d5f7f27ab0558bf`；复现时先核对输出中的 `archive_sha256`。

## 结果

| 检查 | 题面复算 | 随包参考 |
|---|---:|---:|
| 数量差异订单 | 15 | 15 |
| 金额差异订单 | 25 | 10 |
| 未入库订单 | 20 | 20 |
| 无对应订单的入库记录 | 5 | 5 |

全部 15 笔数量差异订单也存在金额差。参考金额集合精确等于复算的金额差集合剔除这 15 笔后的集合。300 笔订单、285 条入库记录的匹配和差集详见[实际 JSON 输出](evidence/workbuddy-procurement.json)。这处差异表明，出题时需显式说明异常标签是否可以重叠、汇总分母是异常类型次数还是唯一订单数。
