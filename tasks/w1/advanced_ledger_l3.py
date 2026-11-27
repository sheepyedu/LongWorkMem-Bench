"""W1 close with an announced records migration and claims against closed transactions."""
import copy
from functools import lru_cache
from pathlib import Path
import random
import shutil
from tempfile import TemporaryDirectory

from . import advanced_ledger as basic
from . import advanced_ledger_score as audit
from .scoring_tables import Table, number
from .world import _csv, _mail, _text

NOTICE = 'site,id,revision,posted,signed,status,source,origin,return_qty,discount_bps'
SUPPORT = 'site,id,source,origin,original_revision,target_site,po,line,net_change,invoice_change'
SOURCE_FOLDERS = ('0626','0630')
MIGRATION = """六月仓储、应付两套明细正本及会签副本在本次报送定版后转入集团电子凭证库。本办公室自周会开始即无法调阅。请在定版前留好必要的经办底稿，可在 notes 或 scratch 保留工作副本。订单、基础资料和收文回执继续留在共享盘。
售后组已通知，七月退货、折让可能只带原库区和六月凭证号。需能追到六月定版时该凭证的有效版本、原签收包装、实际核准的采购行及原已分入各行的人民币金额，不能仅凭六月按采购行汇总后的分录推定。"""
CREDIT_POLICY = """本批售后冲抵通知以 site,id 为键。纳入 posted 和 signed 都不晚于 7 月 8 日、status 为核准或撤回的行；每键取最高数字 revision。撤回不入账，会签稿不入账，重复登载不增加金额。
source=receipt 是退原签收包装。return_qty 为需退回的正数，以 origin 对应六月定版时仓储凭证的原单位和原过账日包装系数折为件，负数计回六月认领的采购行。
source=invoice 是供应商折让。先按 origin 对应六月定版发票在各采购行已分摊的人民币含税额计算。折让总额为六月该笔人民币总额乘 discount_bps/10000，四舍五入到分。按六月核准配票的 part 顺序，每个非末项用其当时已分入的实际人民币金额乘折让比例，四舍五入到分；末项吸收余差。无配票的就记原目标。将折让额以负数计回各笔六月目标行。即使当前期另有认领或汇率变更，售后冲抵仍使用原签收、原入账份额。
补交 out/credit_support.csv，列为 site,id,source,origin,original_revision,target_site,po,line,net_change,invoice_change。每个有效通知的每个六月目标采购行一条，未影响的金额或数量写 0；original_revision 指六月原凭证版本。此次冲抵与普通七月流水一并进入 current 及订单变动桥接。"""


def notice_rows(seed):
    rng = random.Random(f'songlan-vendor-credit/{seed}')
    rows = []
    for site in ('江东','江北','南港','西港'):
        packed = rng.sample([3,13,23,33,43,53,63],3)
        # Every invoice has a signed June split. Some were issued in HKD.
        invoices = [21]+rng.sample([3,30,39,48,57,66],3)
        items = [('receipt',f'W{i+1}') for i in packed] + [('invoice',f'I{i+1}') for i in invoices]
        for idx,(source,origin) in enumerate(items,1):
            qty = 1 if source=='receipt' else 0
            discount = rng.choice([875,1225,1777,2625]) if source=='invoice' else 0
            entry=[site,f'SC-{idx:03}',1,'2025-07-03','2025-07-04','核准',source,origin,qty,discount]
            rows.append(entry)
            if idx==1:
                rows.append(entry.copy())
                rows.append([*entry[:2],3,*entry[3:4],'2025-07-09','撤回',*entry[6:]])
            if idx in (2,5):
                rows.append([*entry[:2],2,*entry[3:4],'2025-07-07','核准',source,origin,qty*2,discount+25 if discount else 0])
            if idx==6:
                rows.append([*entry[:2],2,*entry[3:4],'2025-07-07','撤回',*entry[6:]])
            rows.append([*entry[:2],8,*entry[3:5],'会签',source,origin,qty,discount+100])
    return rows


def publish_credits(work,seed):
    base = work/'input/财务共享/售后'
    _csv(base/'冲抵通知.csv',NOTICE,notice_rows(seed))
    _text(base/'经办口径.txt',CREDIT_POLICY)


def june_evidence_paths(work):
    base=work/'input/财务共享'
    for period in SOURCE_FOLDERS:
        for path in sorted((base/'流转'/period).glob('*.xlsx')):
            if path.name.startswith(('仓库签收','应付归集')):
                yield path


def release(work,turn,variant,level,seed):
    if turn not in basic.PROMPTS:
        return ''
    prompt=basic.release(work,turn,variant,2,seed)
    if turn==1:
        _mail(work,'GL-0527','2025-05-27','finance','电子凭证迁移及售后索引留存',MIGRATION)
        return prompt+' 本季有一次电子凭证库迁移，财务五月底发过留存通知，请依它安排后续工作。'
    if turn==3:
        return prompt+' 电子凭证移库在周会前切换，请完成经办材料留存。'
    if turn==4:
        for path in june_evidence_paths(work):
            path.unlink()
    if turn==5:
        publish_credits(work,seed)
        return prompt+' 售后组另交了本期冲抵通知，请据六月原凭证、按售后经办口径入账并交冲抵依据。'
    return prompt


def originals(docs):
    """Read closed, posted versions in their signed allocation order."""
    orders={(row['site'],row['po'],row['line']): row for row in docs['订单']}
    approvals=audit.routing_orders(docs,'2025-06-30')
    result={}
    for source,sheet in [('receipt','仓储'),('invoice','发票')]:
        for row in audit.bill_versions(docs[sheet],'2025-06-30'):
            key=source,row['site'],row['event']
            raw=(row['site'],row['po'],row['line'])
            targets=approvals.get(key,[(raw,10000)])
            if any(target not in orders for target,_ in targets):
                continue
            if source=='receipt':
                target=targets[0][0]
                factor=1 if row['unit']=='件' else audit.effective(
                    docs['包装'],row['posted'],{'sku':orders[target]['sku'],'unit':row['unit']},'factor')
                result[key]=(row['revision'],[(target,factor)])
            else:
                rate=1 if row['currency']=='CNY' else audit.effective(
                    docs['汇率'],row['posted'],{'currency':row['currency']},'cny')
                total=audit.cents(number(row['amount'])*rate)
                remainder=total
                allocated=[]
                for idx,(target,bps) in enumerate(targets):
                    amt=remainder if idx==len(targets)-1 else audit.cents(total*number(bps)/10000)
                    allocated.append((target,amt))
                    remainder-=amt
                result[key]=(row['revision'],allocated)
    return result


def credit_evidence(work, docs):
    old=originals(docs)
    notices={}
    for row in Table(work/'input/财务共享/售后/冲抵通知.csv').rows:
        if row['status'] not in ('核准','撤回') or max(row['posted'],row['signed'])>'2025-07-08':
            continue
        key=row['site'],row['id']
        if key not in notices or int(row['revision'])>int(notices[key]['revision']):
            notices[key]=row
    evidence=[]
    for row in notices.values():
        if row['status']=='撤回':
            continue
        source=row['source']
        rev,parts=old[source,row['site'],row['origin']]
        percentage=number(row['discount_bps'])/10000
        remainder=audit.cents(sum(v for _,v in parts)*percentage)
        for idx,(target,value) in enumerate(parts):
            net=0
            amount=0
            if source=='receipt':
                net=-number(row['return_qty'])*value
            else:
                rebate=remainder if idx==len(parts)-1 else audit.cents(value*percentage)
                amount=-rebate
                remainder-=rebate
            evidence.append(dict(site=row['site'],id=row['id'],source=source,origin=row['origin'],
                                 original_revision=rev,target_site=target[0],po=target[1],line=target[2],
                                 net_change=net,invoice_change=amount))
    return evidence


def apply_credits(july, evidence, docs):
    rows=copy.deepcopy(july[0])
    by_key={(r['site'],r['po'],r['line']):r for r in rows}
    prices={(r['site'],r['po'],r['line']):number(r['unit_price']) for r in docs['订单']}
    for entry in evidence:
        key=entry['target_site'],entry['po'],entry['line']
        row=by_key[key]
        row['net']+=entry['net_change']
        row['invoiced_amount']+=entry['invoice_change']
        row['qty_diff']=row['net']-number(row['ordered'])
        row['amount_diff']=row['invoiced_amount']-row['net']*prices[key]
        row['flags']=('Q' if row['qty_diff'] else '')+('A' if row['amount_diff'] else '')
    return rows,july[1],july[2]


def reference(run,turn,variant,level,seed):
    work=run/'work'
    working_copy=work/'scratch/六月经办留底'
    if turn!=5:
        audit.reference_turn(run,turn)
        if turn==3:
            base=work/'input/财务共享'
            for path in june_evidence_paths(work):
                if '会签稿' not in path.name:
                    target=working_copy/path.relative_to(base)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(path,target)
        return
    # Reconstruct from the same allowed working copies the office can retain at close.
    with TemporaryDirectory() as tmp:
        union=Path(tmp)
        data=union/'input/财务共享'
        shutil.copytree(work/'input/财务共享'/'收文登记',data/'收文登记')
        shutil.copytree(work/'input/财务共享'/'流转',data/'流转')
        shutil.copytree(working_copy,data,dirs_exist_ok=True)
        docs=audit.signed_tables(union)
        evidence=credit_evidence(work,docs)
        july=apply_credits(audit.accounting(union,'2025-07-08'),evidence,docs)
        june=audit.accounting(union,'2025-06-30')
    out=work/'out'
    bridge,routes=audit.changes((Table(out/'frozen/2025-06.csv').rows,[],june[2]),july)
    for file,fields,rows in [('current.csv',basic.LEDGER,july[0]),('unclaimed.csv',basic.QUEUE,july[1]),
                             ('bridge.csv',basic.BRIDGE,bridge),('routing_changes.csv',basic.ROUTING,routes),
                             ('credit_support.csv',SUPPORT,evidence)]:
        audit.write_rows(out/file,fields,rows)


@lru_cache(maxsize=24)
def expected(seed):
    cuts=dict(audit.expected(2,seed))
    with TemporaryDirectory() as tmp:
        clean=Path(tmp)
        (clean/'inbox').mkdir()
        for turn in (1,2):
            basic.business_files(clean,turn,2,seed,noise=False)
        publish_credits(clean,seed)
        docs=audit.signed_tables(clean)
        evidence=credit_evidence(clean,docs)
        cuts[5]=apply_credits(cuts[5],evidence,docs)
    return cuts,evidence


def checks(run,variant,level,seed):
    cuts,evidence=expected(seed)
    scores=audit.score(run,2,seed,cuts=cuts)
    for item,weight in [('current.warehouse',2),('current.invoices',2),('bridge',1),('routing',2)]:
        key='ledger.'+item
        earned,old,reason=scores[key]
        scores[key]=(weight*earned/old,weight,reason)
    table=Table(run/'snapshots/5/credit_support.csv')
    valid_sources={r.get('source') for r in table.rows} <= {'receipt','invoice'}
    for source in ('receipt','invoice'):
        sites=sorted({r['site'] for r in evidence if r['source']==source})
        good=[]
        business=[r for r in evidence if r['source']==source]
        # Scope parsing to this notice type; an invoice typo cannot invalidate warehouse evidence.
        if valid_sources and not table.error and set(SUPPORT.split(','))<=set(table.headers):
            submitted=copy.copy(table)
            submitted.rows=[r for r in table.rows if r['source']==source]
            if {r['site'] for r in submitted.rows}<=set(sites):
                good=[site for site in sites if audit.matches(submitted,business,SUPPORT,'site',site)]
        scores['ledger.credit.'+source]=(2*len(good)/len(sites),2,
                                       f'R5/credit_support.csv {source}: matched {good} / {sites}')
    return scores
