# W1 · 九轮办公室

需要 Claude Code、Python 3.12、Docker，以及可供宿主复算工作簿的 LibreOffice。独立 Docker VM 须将运行目录设在可写共享挂载中。DeepSeek 读取宿主 ARK_API_KEY，千问沿用适配器的 DEEPSEEK_BASE_URL 与 DEEPSEEK_API_KEY。

```sh
docker build -t longworkmem-office:1 -f w1/Office.Dockerfile .
python -m w1.pilot runs/w1/example --backend docker --level 8
python -m w1.advanced runs/w1/example --details
python -m w1.review runs/w1/example
python -m unittest discover -s w1/tests -t . -v
W1_TEST_DOCKER=1 python -m unittest w1.tests.test_docker -v
```

千问运行时另加 `--model qwen3.8-flash`。独立 VM 的集成测试使用共享路径环境变量 W1_TEST_ROOT。逐轮冻结实际文件和邮件副本。九个过程点合计 30 分，采购、工资、资金交接及预留四项结果合计 70 分。每个检查点以其原子证据的完成比例计分。[九轮交付说明](workflow.md)

工资簿复评要求 LibreOffice 成功完成所有已生成的变更用例。进程退出异常、超时或缺少转换文件时会提示复评；可在恢复 Calc 后重放同一份冻结交付。

公开实例为 17217/A，每轮可以继续查阅和执行。历史 ERP 批数窗口可用 `--erp-window` 显式复现，`--limit N` 仅供成本控制；两者均记录为实验条件。
