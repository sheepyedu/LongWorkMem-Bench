# S1 · 跨区器材联赛

需要 Python 3.12、Claude Code 和 Docker。无网络业务容器生成各班公文并接收文本 JSON 单据，模型工具列表为空。DeepSeek 读取 ARK_API_KEY，千问读取宿主 DEEPSEEK_BASE_URL、DEEPSEEK_API_KEY。

```sh
docker build -f s1/Circuit.Dockerfile -t longworkmem-circuit:1 .
S1_TEST_DOCKER=1 python -m unittest s1.tests.test_engine -v
python -m s1.circuit runs/s1/example --models deepseek qwen
python -m s1.circuit_review runs/s1/example/handover-Q2-D10-L2-17217-A-deepseek
python -m unittest discover -s s1/tests -t . -v
```

每个模型输出独立目录。复评按 manifest 的解析器及评分版本核对每轮请求、回答和已登记单据。十个赛区等权。每区在第 1、2、3、6 班分别登记两队的四个字段，另在第 4、5、7、8 班按每队器材配套和送达各计一次。公开主条件在第 40 轮交接自写 note，41 轮开新会话。可显式用 `--history continuous` 做同材料全历史对照。使用不同模型调用路由时请披露推理配置。

用 `python -m s1.circuit_registration_audit RUN` 可复核历史评分版本 2 的登记格式敏感性。它只展开唯一且名称等于本轮指定赛段的包装层，在原回答上计算替代分，并核对订单分不变。正式成绩沿用原规则。
