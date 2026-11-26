# 设备服务台工单交换工具

班组在工位根目录运行 Python 3，仅依赖标准库。

    python3 project/tickets.py import-csv scratch/trial.sqlite input/legacy.csv
    python3 project/tickets.py export-csv scratch/trial.sqlite scratch/trial.csv

导入命令可在空路径建库。每次导入按 CSV 行序追加，导出按原先的入库顺序返回全量旧台账。UTF-8 表头为 number,dept,status，号码输出为十进制整数，部门和状态原样保留，使用标准 CSV 引号。每个班组都有只认这套接口的旧脚本。

data/tickets.sqlite 是交班时的业务库，input/initial.sqlite 是封存的同版原库。日常升级直接维护业务库。input/legacy.csv 是接口联测文件，可在 scratch/ 下另起空库演练。

project/ 内的代码、data/ 里的库和日常工作文件会保留到下一次交班。业务材料在 input/，报送件放 out/。可在 notes/ 保存维护笔记。
