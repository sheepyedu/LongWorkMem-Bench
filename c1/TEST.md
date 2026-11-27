# C1 · 七轮工时结算与保证金交割

需 Claude Code、Docker 及镜像 python:3.12-slim。凭据由宿主的 C1_UPSTREAM_KEY 或隐藏输入提供。独立 Docker VM 需在共享可写目录下运行，可用 C1_TEST_ROOT 指定同一 VM 可写的临时评分路径。下列单场使用安装环境中的默认 DeepSeek 路由。

```sh
docker pull python:3.12-slim
python -m c1.calibrate runs/c1/example
python -m c1.settlement_grade runs/c1/example/17217-A --backend docker
python -m c1.review runs/c1/example/17217-A
C1_TEST_DOCKER=1 python -m unittest discover -s c1/tests -t . -v
```

千问使用 `--model qwen3.8-flash --url "$QWEN_CHAT_COMPLETIONS_URL"`，URL 指向完整的 chat/completions 端点。公开实例固定三级、17217/A，第 5 和第 7 轮更换班组。每轮结束时评分。可另用 `--dispatch-after 2` 研究提前签收，并用 `--limit N` 控制该次实验成本。独立评分器核验签收水位、逐笔分摊、归档及保证金交割，并用新来件复跑代码。结果含 checks、valid、missing、infrastructure，以及错误字段的缺行、多行与重数。显式实验预算耗尽的新版 run 保留 observed_points 与未到达轮次，正式 total 留空。
