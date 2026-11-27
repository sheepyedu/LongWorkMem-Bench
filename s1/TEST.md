# S1 · 跨区器材联赛

需要 Python 3.12 与 Claude Code。宿主生成各班公文并接收文本 JSON 单据，模型工具列表为空。DeepSeek 读取 ARK_API_KEY，千问读取宿主 DEEPSEEK_BASE_URL、DEEPSEEK_API_KEY。

```sh
python -m s1.circuit runs/s1/example --models deepseek qwen --seeds 101 --desks 10 --qualifiers 2 --level 2
python -m s1.circuit_review runs/s1/example/Q2-D10-L2-101-A-deepseek
python -m unittest discover -s s1/tests -t . -v
```

每个模型输出独立目录。复评按 manifest 的解析器及评分版本核对每轮请求、回答和已登记单据。十个赛区等权。每区在第 1、2、3、6 班分别登记两队的四个字段，另在第 4、5、7、8 班按每队器材配套和送达各计一次。连续会话为正式主条件，按区分会话、换班仅用于对照。
