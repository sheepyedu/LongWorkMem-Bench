"""W1 consignment settlement batches and the signed account-review sheets."""
from decimal import Decimal
from datetime import datetime
from io import BytesIO
import random
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook
from openpyxl.comments import Comment

from . import advanced_ledger as basic
from . import advanced_ledger_l3 as migration
from .world import _mail, _text

FORM='site,batch,bill,status,tickets'
BATCHES=('唯一','局部','重复','混合','局部','唯一','重复')
# Printed statements specify totals only. These layouts create realistic locally indistinguishable lots.
LAYOUTS={
    '唯一': ([(4,2),(3,1),(4,3),(6,2),(3,2),(5,2),(2,1),(3,3)], [(7,0),(1,2),(3,4),(5,6)]),
    '局部': ([(7,3),(1,1),(6,2),(1,3),(7,3),(4,2),(4,1),(4,3)], [(6,4),(7,2),(0,3),(1,5)]),
    '重复': ([(7,1),(1,3),(3,1),(7,2),(4,1),(1,3),(4,1),(4,2)], [(4,2),(7,6),(1,3),(5,0)]),
    '混合': ([(7,1),(6,3),(1,3),(4,3),(2,3),(2,2),(4,2),(2,2),(5,2)], [(2,8,1),(7,5),(4,0),(6,3)]),
}
SLIPS='行类,site,batch,ticket,po,line,qty,amount'
BILLS='行类,site,batch,bill,print_line,ticket_count,total_qty,total_amount,复核栏'
CORRECTIONS='site,batch,bill,revision,signed,status,total_qty,total_amount'
ENDORSEMENTS='site,batch,bill,ticket,revision,signed,status,action'

POLICY="""松岚设备｜寄售转购月结办法
四个库区的寄售备件在实际消耗且供应商月结单能匹配领用联后转购，财务同时确认净入件数和人民币含税票款。此为本期采购的另一条来源，和常规 ERP 流水合并在同一 current.csv；不占用普通 ERP 的事件号。六月领用联及汇总结算联在周会前与 ERP 一起移库，后续会涉及原批次的复核，请留好经办底稿。
文件柜 input/财务共享/寄售。0626 的《消耗联》《对账联》为盖章纸页重录的正本，《内部讨论》只供备查。每页以“领用”“结算”行标明业务明细，合并表头的库区和对账批次向下沿用；小计行不计入。对账批次在不同库区可重号。同组内每张领用联有唯一编号，含唯一采购行、件数、含税额。
按 site,batch 整批核对。每张结算单必须依其 ticket_count 张数、total_qty 件数和 total_amount 人民币金额同时一致，逐分精确。组中每张领用联必须且只能交给本组的一张结算单。先以全部结算单同时可行的整批分派为准，再逐单判断。若整批无可行分派，各单均为 CONFLICT；若某张单在所有可行分派中拿到的领用联号集合都相同，则该单 BOOKED；若有不同集合则该单 MULTIPLE 暂挂。即使集合对应的金额或采购行相同，联号不同仍属多解。禁止靠文件行序任选其中一种。
手工签注随正本保留在《对账联》复核栏单元格批注中。签章作者为“应付复核岗”的签注才有约束力，按批注内签发日及当前截点办理（六月30日、七月8日均含当天）。每条的“指定/排除”联号只约束该结算单。首批纸页签注计第1版。后续按到件《复核移交》的“数字勘误”和“签注变更”两页办理。文件里的会签、晚于截点的签发不生效。数字勘误按 site,batch,bill 取最高已签版，覆盖该单核对件数、金额，原随附件数张数不变。签注变更按 site,batch,bill,ticket 取最高已签版，覆盖这一对的旧约束；解除表示这对不再受限。指定、排除或解除都必须以“签发”的日戳为准。
out/consignment.csv 栏位 site,batch,bill,status,tickets，每期所有供应商结算单一单一行。BOOKED 填确已认领的领用联号，以 | 分隔；暂挂两类 tickets 留空。只有 BOOKED 把各联的 qty 和 amount 计入其所指本库区采购行。两类暂挂单进入统一 out/unclaimed.csv，source=invoice，id 填 bill，po 填原批次号，line 填该单 print_line。七月两期都存在的寄售票，实际目标行集合变动也进 out/routing_changes.csv，以 invoice 和 bill 为索引，暂挂写 PENDING。"""


def forms(seed):
    rng=random.Random(f'case-VMI/{seed}')
    base=300+abs(seed)%100
    groups=[]
    labels=rng.sample(range(101,950),len(BATCHES))
    for site in ('江东','江北','南港','西港'):
        rng.shuffle(labels)
        for idx,layout in enumerate(BATCHES):
            batch=f'J{labels[idx]}'
            facts,groups_of_ids=LAYOUTS[layout]
            serials=rng.sample(range(1110,9900),len(facts)+4)
            qty_factor=rng.randint(1,3)
            cents_factor=rng.randint(1020,5880)
            fee=rng.randrange(1,100)
            positions=rng.sample(range(72),len(facts))
            slips=[]
            for j,(units,mult) in enumerate(facts):
                pos=positions[j]
                price=(Decimal(units*cents_factor+mult*fee)/100)
                slips.append((f'L{serials[j]}',f'PO-{base+pos//2}',1+pos%2,
                              mult*qty_factor,price))
            printed=rng.sample(range(1,5),4)
            bills=[]
            for j,indices in enumerate(groups_of_ids):
                name=f'JS-{batch}-{serials[-4+j]}'
                qty=sum(slips[k][3] for k in indices)
                amount=sum(slips[k][4] for k in indices)
                bills.append((name,printed[j],len(indices),qty,amount))
            groups.append((site,batch,idx,slips,bills))
    return groups


def pagebook(path, kind, groups, *, draft=False):
    book=Workbook()
    sheet=book.active
    sheet.title='领用留底' if kind=='领用' else '供应商结算'
    schema=SLIPS if kind=='领用' else BILLS
    sheet.append([sheet.title+'｜本期财务接收页'])
    sheet.append(['金额人民币元，数量件。合并批头向下沿用。复核签注随单保管。'])
    sheet.append(schema.split(','))
    for site,batch,idx,slips,bills in groups:
        start=sheet.max_row+1
        records=slips if kind=='领用' else bills
        sequence=list(enumerate(records))
        random.Random(f'{site}/{batch}/{kind}').shuffle(sequence)
        subtotal=Decimal(0)
        for pos,(j,record) in enumerate(sequence):
            shown=list(record)
            if kind=='领用':
                shown[-1]=str(shown[-1])
            else:
                if idx==3 and j==1:shown[-1]+=Decimal('0.01')
                shown[-1]=str(shown[-1])
                shown.append('')
            subtotal+=Decimal(shown[4])
            sheet.append([kind,site if pos==0 else None,batch if pos==0 else None,*shown])
            if kind=='结算':
                author,ticket,day,action=None,None,'2025-06-25','指定'
                if idx==2 and j==0:author,ticket='应付复核岗',4
                if idx==4 and j==0:author,ticket,action='应付复核岗',4,'排除'
                if idx==5 and j==1:author,ticket,day,action='应付复核岗',1,'2025-07-05','排除'
                if idx in (0,1,6) and j==2:author,ticket,action='供应商对账员',0,'指定'
                if author:
                    cell=sheet.cell(sheet.max_row,9)
                    cell.comment=Comment(f'{day}／{action}／{slips[ticket][0]}',author)
        end=sheet.max_row
        for col in (2,3):
            sheet.merge_cells(start_row=start,start_column=col,end_row=end,end_column=col)
        sheet.append(['页小计',site,batch,None,None,None,
                      sum(x[3] for x in records),str(subtotal)])
    if draft:
        sheet['A1']='讨论稿。供应商临时试配，未盖章。'
    book.properties.created=book.properties.modified=datetime(2025,1,1)
    payload=BytesIO()
    book.save(payload)
    path.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(payload) as original, ZipFile(path,'w') as stable:
        for name in original.namelist():
            data=original.read(name)
            if name=='docProps/core.xml':
                data=re.sub(rb'(<dcterms:modified[^>]*>)[^<]+',rb'\g<1>2025-01-01T00:00:00Z',data)
            stable.writestr(ZipInfo(name,date_time=(2025,1,1,0,0,0)),data,compress_type=ZIP_DEFLATED)


def publish(work,turn,seed):
    cabinet=work/'input/财务共享/寄售'
    if turn==4:
        for path in (cabinet/'0626').glob('*.xlsx'):
            path.unlink()
        for path in (cabinet/'0630').glob('*.xlsx'):
            path.unlink()
        return
    if turn not in (1,2,5):return
    groups=forms(seed)
    if turn==1:
        _text(cabinet/'寄售转购办法.txt',POLICY)
        _mail(work,'AP-0612','2025-06-12','ap','寄售物料转购及供应商签章传递',
              '本期寄售业务并入采购底账。财务共享寄售柜里有转购办法。供应商转来的是成组对账联，逐张转购以前要确保不会重复占用同组另一张票的消耗联。')
        pagebook(cabinet/'0626/消耗联.xlsx','领用',groups)
        pagebook(cabinet/'0626/对账联.xlsx','结算',groups)
        pagebook(cabinet/'0626/内部讨论.xlsx','结算',groups[::3],draft=True)
        return
    amendments,notes=[],[]
    for site,batch,idx,slips,bills in groups:
        def signed(bill,slip,rev,action,day,status='签发'):
            notes.append((site,batch,bills[bill][0],slips[slip][0],rev,day,status,action))
        if turn==2:
            if idx==1:signed(0,4,2,'指定','2025-06-30')
            if idx==2:signed(2,1,2,'指定','2025-06-30')
            if idx==3:
                name,_,_,qty,amount=bills[1]
                amendments.extend([(site,batch,name,2,'2025-06-30','签发',qty,str(amount)),
                                   (site,batch,name,8,'2025-06-30','会签',qty+1,str(amount))])
            if idx==4:signed(0,4,2,'解除','2025-06-30')
            if idx==6:
                signed(0,4,2,'指定','2025-06-30')
                signed(1,4,2,'指定','2025-06-30')
            signed(3,0,9,'指定','2025-07-12')
        else:
            if idx==1:signed(0,4,3,'解除','2025-07-04')
            if idx==2:signed(0,4,3,'解除','2025-07-04')
            if idx==4:signed(0,4,3,'指定','2025-07-04')
            if idx==6:signed(1,4,3,'解除','2025-07-04')
            signed(3,1,10,'指定','2025-07-04','会签')
    folder='0630' if turn==2 else '0708'
    basic.workbook(cabinet/f'{folder}/复核移交.xlsx',{'数字勘误':(CORRECTIONS,amendments),
                                            '签注变更':(ENDORSEMENTS,notes)})


def release(work,turn,variant,level,seed):
    prompt=migration.release(work,turn,variant,3,seed)
    publish(work,turn,seed)
    if turn==1:return prompt+' 寄售转购也归这套采购账，请按本季专门办法一并入账并交逐单认领表。'
    if turn==2:return prompt+' 寄售复核岗已送签章勘误和签注变更，请连同逐单认领表一起更新。'
    if turn==3:return prompt+' 寄售逐单认领表同时定版 out/frozen/consignment-06.csv，六月签章原件也随主账移库。'
    if turn==5:return prompt+' 寄售组本月的复核移交已签收，同步办完本批转购清单、原表变动与未认领。'
    return prompt


def reference(run,turn,variant,level,seed):
    from .advanced_consignment import reference_turn
    reference_turn(run,turn,variant,seed)


def checks(run,variant,level,seed):
    from .advanced_consignment import score
    return score(run,variant,seed)
