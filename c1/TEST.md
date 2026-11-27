# C1 · 七轮工时结算与保证金交割

需 Claude Code、Docker 及镜像 python:3.12-slim。凭据由宿主的 C1_UPSTREAM_KEY 或隐藏输入提供。独立 Docker VM 需在共享可写目录下运行，可用 C1_TEST_ROOT 指定同一 VM 可写的临时评分路径。下列单场使用安装环境中的默认 DeepSeek 路由。

```sh
docker pull python:3.12-slim
python -m c1.calibrate runs/c1/example --seeds 101 --variants A --limit 180
python -m c1.settlement_grade runs/c1/example/101-A --backend docker
python -m c1.review runs/c1/example/101-A
C1_TEST_DOCKER=1 python -m unittest discover -s c1/tests -t . -v
```

千问使用 `--model qwen3.8-flash --url "$QWEN_CHAT_COMPLETIONS_URL"`，URL 指向完整的 chat/completions 端点。固定三级、两次调用取件及两次换班后，在两家模型间配对种子和 A/B 口径。取件版占三分之二，轮末版占三分之一。独立评分器核验签收水位、逐笔分摊、归档及保证金交割，并用新来件复跑代码。完整结果含两套 checks 及 valid、missing、infrastructure 字段。
