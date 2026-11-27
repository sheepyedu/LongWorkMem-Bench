# 测试指南

从仓库根目录运行。Python 3.12，依赖安装 `python -m pip install -r w1/requirements.txt`，W1 工作簿需 LibreOffice Calc。

```sh
python -m unittest discover -v
python -m unittest discover -s w1/tests -t . -v
python -m unittest discover -s c1/tests -t . -v
python -m unittest discover -s s1/tests -t . -v
```

## W1 跨月关账

[W1 环境、运行命令、重算及测试](w1/TEST.md)

## C1 工单事件库

[C1 沙箱、工程及结算版本测试](c1/TEST.md)

## S1 跨幕卡牌联赛

[S1 主赛、交接与长赛季测试](s1/TEST.md)
