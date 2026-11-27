"""Phased procurement office for the W1 calibration levels."""
from datetime import datetime
from decimal import Decimal
from io import BytesIO
import random
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from openpyxl import Workbook

from .world import _archive, _csv, _mail, _office_files, _text

SCHEMAS = {
    '订单': 'site,po,line,project,sku,ordered,unit_price',
    '仓储': 'site,event,revision,posted,approved,status,po,line,unit,qty',
    '发票': 'site,event,revision,posted,approved,status,po,line,currency,amount',
    '认领': 'source,site,event,revision,signed,decision,part,target_site,po,line,bps',
    '包装': 'sku,unit,effective,factor',
    '汇率': 'currency,effective,cny',
}
LEDGER = 'site,po,line,project,ordered,net,invoiced_amount,qty_diff,amount_diff,flags'
QUEUE = 'site,source,id,po,line'
MEETING = 'project,total_lines,exception_lines,qty_lines,amount_lines,exposure'
PRIORITY = 'project,rank,site,po,line,flags'
BRIDGE = 'site,po,line,net_change,invoice_change'
ROUTING = 'site,source,id,before,after'

PROMPTS = {
    1: '接手松岚设备跨库采购。先按六月底可用正本做 current 和待认领清单，交付格式见财务共享的月结交接说明。来件中的批复和各部门口径请一并留档。',
    2: '仓库、应付组又送来六月替换页与认领处理。仍按六月截点更新原工作底表及待认领清单，财务下午按这版关账。',
    3: '六月已关账。请将上轮实际报送的 current.csv 和待认领清单副本原样定版到 out/frozen/2025-06.csv 和 out/frozen/unclaimed-06.csv，保留原工作件。',
    4: '管理层周会临时插单：依六月报送版、按管理会计此前发的例会口径，交 out/meeting.csv 和 out/priority.csv。只交会前文件。',
    5: '回到采购账，七月 8 日进来的文件都已登记。按该日截点更新 current 和待认领，六月定版供审计继续调阅。请同时按月结说明完成两份跨期变动表。',
}


def workbook(path, sheets):
    """Stable OOXML bytes keep paired worlds equal, including ZIP and core timestamps."""
    book = Workbook()
    book.remove(book.active)
    book.properties.created = book.properties.modified = datetime(2025, 1, 1)
    for name, (fields, rows) in sheets.items():
        sheet = book.create_sheet(name)
        sheet.append(fields.split(','))
        for row in rows:
            sheet.append(list(row))
    raw = BytesIO()
    book.save(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(raw) as source, ZipFile(path, 'w', ZIP_DEFLATED) as output:
        for name in source.namelist():
            data = source.read(name)
            if name == 'docProps/core.xml':
                import re
                data = re.sub(rb'(<dcterms:modified[^>]*>)[^<]+', rb'\g<1>2025-01-01T00:00:00Z', data)
            info = ZipInfo(name, date_time=(2025, 1, 1, 0, 0, 0))
            output.writestr(info, data, compress_type=ZIP_DEFLATED)


def batches(level, seed):
    rng = random.Random(f'songlan-procurement/{seed}')
    sites = ('江东', '江北') if level == 1 else ('江东', '江北', '南港', '西港')
    count = 32 if level == 1 else 72
    result = {turn: {tab: [] for tab in SCHEMAS} for turn in (1, 2, 5)}
    master = result[1]
    for sku_no in range(8):
        for start, factor in [('2025-01-01', 4 + sku_no % 3), ('2025-06-16', 6 + sku_no % 3)]:
            master['包装'].append((f'S{sku_no}', '箱', start, factor))
    master['汇率'] += [('HKD', '2025-01-01', 0.9123), ('HKD', '2025-06-16', 0.9237),
                       ('HKD', '2025-07-01', 0.9141)]
    base_number = 300 + abs(seed) % 100
    items = ['甲', '乙', '丙']
    for site_index, site in enumerate(sites):
        other = sites[(site_index + 1) % len(sites)]
        for i in range(count):
            po = f'PO-{base_number+i//2}'
            line = 1 + i % 2
            sku_no = rng.randrange(8)
            price = Decimal(rng.randrange(415, 12455)) / 100
            qty = rng.randrange(12, 49)
            master['订单'].append((site, po, line, items[(i + site_index) % 3], f'S{sku_no}', qty, str(price)))
            seq = i + 1
            old = f'迁-{seq}'
            raw_po = old if i % 11 == 1 else po
            day = '2025-06-12' if i % 2 else '2025-06-20'
            val = 2 if level == 2 and i % 5 == 3 else qty // 2
            unit = '箱' if level == 2 and i % 5 == 3 else '件'
            factor = (4 if day < '2025-06-16' else 6) + sku_no % 3 if unit == '箱' else 1
            receipt = (site, f'W{seq}', 1, day, day, '有效', raw_po, line, unit, val)
            master['仓储'].append(receipt)
            if i % 7 == 0:
                master['仓储'].append(receipt)
            rest = qty - val * factor - (1 if i % 9 == 0 else 0)
            master['仓储'].append((site, f'B{seq}', 1, day, day, '有效', po, line, '件', rest))
            currency = 'HKD' if level == 2 and i % 4 == 1 else 'CNY'
            amount = price * qty + (Decimal('0.03') if i % 8 == 2 else 0)
            invoice = (site, f'I{seq}', 1, day, day, '有效', raw_po, line, currency, str(amount))
            master['发票'].append(invoice)
            if i % 9 == 4:
                master['发票'].append(invoice)
            if i % 8 == 0:
                # Submitted correction with a higher revision, never released at June close.
                master['仓储'].append((site, f'W{seq}', 4, day, '2025-07-09', '撤销', raw_po, line, unit, val))
            if i % 10 == 2:
                result[2]['仓储'].append((site, f'W{seq}', 2, day, '2025-06-30', '有效', raw_po, line, unit, val-1))
                result[2]['发票'].append((site, f'I{seq}', 2, day, '2025-06-30', '撤销', raw_po, line, currency, str(amount)))
            if i % 13 == 4:
                result[2]['仓储'].append((site, f'T{seq}', 1, '2025-06-28', '2025-06-30', '有效', po, line, '件', -2))
            if i % 11 == 1:
                for source in ('receipt','invoice'):
                    event = ('W' if source == 'receipt' else 'I') + str(seq)
                    target = other if level == 2 and source == 'invoice' else site
                    claim = [source, site, event, 1, '2025-06-30', '核准', 1, target, po, line, 10000]
                    result[2]['认领'].append(claim)
                    if i % 22 == 1:
                        result[5]['认领'].append([source, site, event, 2, '2025-07-04', '撤回', 1, target, po, line, 10000])
                    result[2]['认领'].append([source, site, event, 9, '2025-06-29', '提议', 1, other, po, line, 10000])
            if level == 2 and i % 9 == 3:
                # Cross-entity consolidated invoice with a signed two-line allocation.
                for part, target, share in [(1,site,3725), (2,other,6275)]:
                    result[2]['认领'].append(('invoice',site,f'I{seq}',1,'2025-06-30','核准',part,target,po,line,share))
                result[5]['认领'].append(('invoice',site,f'I{seq}',2,'2025-07-07','核准',1,other,po,line,10000))
            if i % 5 == 0:
                result[5]['仓储'].append((site, f'B{seq}', 2, '2025-07-03', '2025-07-08', '有效', po, line, '件', rest+1))
            if i % 7 == 2:
                result[5]['发票'].append((site, f'C{seq}', 1, '2025-07-02', '2025-07-08', '有效', po,line,currency,'-1.37'))
            if i % 15 == 3:
                # A July-posted line remains outside the June ledger even if signed in June.
                result[2]['仓储'].append((site,f'L{seq}',1,'2025-07-08','2025-06-30','有效',po,line,'件',1))
            if i % 23 == 5:
                for source, prefix, last in [('仓储','U',('件',2)),('发票','V',('CNY','33.19'))]:
                    master[source].append((site,prefix+str(seq),1,day,day,'有效',old,line,*last))
    return result


GUIDE = """采购财务共享中心｜六月关账交接
资料入口为 input/财务共享/收文登记，每批签收的文件/页签是本期正本；其余流转件作业务备查。登记路径均相对 input/财务共享。
采购行以 site、po、line 三项定位，同一单号可在其他库区使用。件为库存基准，仓储与发票用各自 site,event 唯一识别，跨文件重复只计一次。
截点包含当日。取 posted 和 approved 都不晚于截点的最高数字 revision；其中 status=撤销 则该凭证不再入账。每一版是全量替换。
包装按实际 posted 当日对 SKU 生效的最近版本换算（件=1）。非人民币发票亦按 posted 当日对应货币最近生效牌价，先将原币含税额换为人民币、四舍五入到分。CNY 等值。负数照符号处理。
认领单针对 source,site,event，source 仅用 receipt / invoice。先排除提议及晚于截点的签发记录；余下选最高数字 revision。撤回即回到原单据所列库区、订单和行号。核准的 part 指向目标采购行，优先于原载，bps 是万分比。配票按 part 顺序分摊人民币金额，除末项外逐笔四舍五入到分，末项吸收差额。仓储核准均为整笔。
未能匹配采购行的在途有效凭证全列 out/unclaimed.csv（site,source,id,po,line，使用原始引用，零行仍交表头）。已撤销凭证无需认领。
工作底表 out/current.csv 每个采购行一行，栏位为 site,po,line,project,ordered,net,invoiced_amount,qty_diff,amount_diff,flags。qty_diff=net-ordered；amount_diff=人民币开票额-net×订单价，元到分。flags 用 Q/A/QA/空 表示数量/金额/两类/正常。无活动流水的采购行也保留。
七月更新时，out/bridge.csv 的 site,po,line,net_change,invoice_change 仅列与六月冻结比较净收或人民币票款有变化的采购行，记录七月减六月。另交 out/routing_changes.csv（site,source,id,before,after）：只列两期均有效、实际目标采购行集合改变的凭证。目标编码为 site/po/line，多目标按字符顺序用 | 并列，未认领写 PENDING。金额变动或比例变化而目标相同不列。"""

MEETING_RULE = """周会按采购项目汇总，三项目均须列出。out/meeting.csv 栏位 project,total_lines,exception_lines,qty_lines,amount_lines,exposure。异常行按采购行去重，两类行数各算一次；风险金额 exposure 为逐行 amount_diff 取绝对值后求和。out/priority.csv 栏位 project,rank,site,po,line,flags；每项目取至多三个异常采购行，依次按金额差绝对值降序、数量差绝对值降序、site 和 po 字符升序、line 数字升序。rank 从 1 起。"""


def business_files(work, turn, level, seed, *, noise):
    if turn not in (1, 2, 5):
        return
    base = work / 'input/财务共享'
    batch_no = {1:'0626', 2:'0630', 5:'0708'}[turn]
    if turn == 1:
        _text(base / '月结交接说明.txt', GUIDE)
        _mail(work, 'GL-0605', '2025-06-05','finance','例会跟催表沿用本季度口径', MEETING_RULE)
        if noise:
            _archive(work)
            _office_files(work)
            for index in range(12 if level == 1 else 30):
                month = 1 + index % 5
                department = ('应付','仓配','采购')[index%3]
                b = [(f'旧{month}-{i:04}', 5 + i % 19, 90 + (i * 11 + seed) % 320) for i in range(36)]
                workbook(base / '资料柜' / department / f'{index+1:02}月度交接.xlsx',
                         {'交接清单': ('ref,qty,amount', b), '盘点抽样': ('ref,qty,amount', b[::3])})
    rows = batches(level,seed)[turn]
    paths = []
    for name, tabs in [('订货与基础资料', ('订单','包装','汇率')), ('仓库签收', ('仓储',)), ('应付归集', ('发票','认领'))]:
        body = {tab:(SCHEMAS[tab],rows[tab]) for tab in tabs if rows[tab]}
        if not body:
            continue
        path = f'流转/{batch_no}/{name}.xlsx'
        if noise:
            rejected = f'流转/{batch_no}/{name}（会签稿）.xlsx'
            workbook(base/rejected,{tab:(fields, data[1:]) for tab,(fields,data) in body.items()})
            paths.extend((rejected,tab,'会签') for tab in body)
        paths.extend((path,tab,'签收') for tab in body)
        workbook(base/path, body)
    _csv(base/'收文登记'/f'{batch_no}.csv','file,sheet,status',paths)


def release(work, turn, variant, level, seed):
    if turn not in PROMPTS:
        return ''
    business_files(work,turn,level,seed,noise=True)
    return PROMPTS[turn]


def reference(run, turn, variant, level, seed):
    from .advanced_ledger_score import reference_turn
    reference_turn(run, turn)


def checks(run, variant, level, seed):
    from .advanced_ledger_score import score
    return score(run, level, seed)
