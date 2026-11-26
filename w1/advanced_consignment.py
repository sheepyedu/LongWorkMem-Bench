"""Host-only settlement of signed consignment pages and W1 stage checks."""
from collections import defaultdict
from contextlib import closing
from functools import lru_cache
from itertools import combinations
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

from . import advanced_ledger as basic
from . import advanced_ledger_score as audit
from . import advanced_ledger_l3 as migration
from . import advanced_ledger_l4 as paper
from .scoring_tables import Table, number

JUNE='2025-06-30'
JULY='2025-07-08'
FORM_KEY=('site','batch','bill')
CABINET=Path('input/财务共享/寄售')


def keyed(row):
    return tuple(row[field] for field in FORM_KEY)


def read_pages(path,kind):
    rows=[]
    with closing(load_workbook(path,data_only=True)) as book:
        page=book.active
        headers=[cell.value for cell in page[3]]
        for cells in page.iter_rows(min_row=4):
            if cells[0].value!=kind:
                continue
            row=dict(zip(headers,[cell.value for cell in cells]))
            if row['site']:
                site,batch=row['site'],row['batch']
            row['site'],row['batch']=site,batch
            if kind=='结算':
                annotation=cells[8].comment
                if annotation and annotation.author=='应付复核岗':
                    row['annotation']=annotation.text.split('／')
            rows.append(row)
    return rows


def review_records(cabinet,cutoff,bills):
    amendments={}
    notes={}
    for row in bills:
        if 'annotation' in row:
            day,action,ticket=row['annotation']
            if day<=cutoff:
                notes[(*keyed(row),ticket)]=(1,action)
    for path in sorted(cabinet.glob('*/复核移交.xlsx')):
        with closing(load_workbook(path,data_only=True,read_only=True)) as book:
            for name in ('数字勘误','签注变更'):
                it=iter(book[name].values)
                header=next(it)
                for values in it:
                    row=dict(zip(header,values))
                    if row['status']!='签发' or row['signed']>cutoff:
                        continue
                    if name=='数字勘误':
                        store=amendments
                        key=keyed(row)
                        update=(row['total_qty'],row['total_amount'])
                    else:
                        store=notes
                        key=(*keyed(row),row['ticket'])
                        update=row['action']
                    revision=int(row['revision'])
                    if key not in store or revision>store[key][0]:
                        store[key]=(revision,update)
    return amendments,notes


def resolve_group(slips,bills,amendments,notes):
    """Track per-bill consensus across every complete disjoint allocation."""
    options={}
    by_id={r['ticket']:r for r in slips}
    tickets=list(by_id)
    for bill in bills:
        key=keyed(bill)
        qty,amt=amendments.get(key,(0,(bill['total_qty'],bill['total_amount'])))[1]
        required={ticket for (*prefix,ticket),(_,action) in notes.items()
                  if tuple(prefix)==key and action=='指定'}
        forbidden={ticket for (*prefix,ticket),(_,action) in notes.items()
                   if tuple(prefix)==key and action=='排除'}
        options[bill['bill']]=[]
        for parts in combinations(tickets,int(bill['ticket_count'])):
            if required.issubset(parts) and forbidden.isdisjoint(parts):
                if sum(number(by_id[k]['qty']) for k in parts)==number(qty) and (
                        sum(number(by_id[k]['amount']) for k in parts)==number(amt)):
                    options[bill['bill']].append(frozenset(parts))
    order=sorted(options,key=lambda bill:len(options[bill]))
    solutions=defaultdict(set)
    def visit(depth,remaining,assignment):
        if depth==len(order):
            if not remaining:
                for key,value in assignment.items():
                    solutions[key].add(value)
            return
        bill=order[depth]
        for bundle in options[bill]:
            if bundle<=remaining:
                assignment[bill]=bundle
                visit(depth+1,remaining-bundle,assignment)
    visit(0,frozenset(tickets),{})
    for bill in bills:
        choices=solutions[bill['bill']]
        status='CONFLICT' if not choices else ('BOOKED' if len(choices)==1 else 'MULTIPLE')
        picked=sorted(next(iter(choices))) if status=='BOOKED' else []
        yield dict(site=bill['site'],batch=bill['batch'],bill=bill['bill'],status=status,
                   tickets='|'.join(picked)),[by_id[ticket] for ticket in picked],bill['print_line']


def resolve(work,cutoff):
    cabinet=work/CABINET
    slips=read_pages(cabinet/'0626/消耗联.xlsx','领用')
    bills=read_pages(cabinet/'0626/对账联.xlsx','结算')
    amendments,notes=review_records(cabinet,cutoff,bills)
    def group(rows):
        result=defaultdict(list)
        for row in rows:
            result[(row['site'],row['batch'])].append(row)
        return result
    per_batch=group(slips)
    forms,postings,pending,destinations=[],[],[],{}
    for group_key,items in group(bills).items():
        for form,accepted,line in resolve_group(per_batch[group_key],items,amendments,notes):
            forms.append(form)
            site,batch,bill=keyed(form)
            key='invoice',site,bill
            if not accepted:
                destinations[key]='PENDING'
                pending.append(dict(site=site,source='invoice',id=bill,po=batch,line=line))
                continue
            targets=set()
            for slip in accepted:
                targets.add(f"{site}/{slip['po']}/{slip['line']}")
                postings.append(dict(target_site=site,po=slip['po'],line=slip['line'],
                                     net_change=number(slip['qty']),invoice_change=number(slip['amount'])))
            destinations[key]='|'.join(sorted(targets))
    return forms,postings,pending,destinations


def combined(work,cutoff,period,docs):
    forms,postings,pending,routes=resolve(work,cutoff)
    ledger,queue,destinations=migration.apply_credits(period,postings,docs)
    return (ledger,queue+pending,{**destinations,**routes}),forms


@lru_cache(maxsize=24)
def expected(seed):
    basecuts,_=migration.expected(seed)
    cuts={}
    forms={}
    with TemporaryDirectory() as tmp:
        clean=Path(tmp)
        (clean/'inbox').mkdir()
        for turn in (1,2,5):
            basic.business_files(clean,turn,2,seed,noise=False)
            paper.publish(clean,turn,seed)
            cuts[turn],forms[turn]=combined(clean,JULY if turn==5 else JUNE,basecuts[turn],
                                            audit.signed_tables(clean))
    return cuts,forms


def reference_turn(run,turn,variant,seed):
    work=run/'work'
    out=work/'out'
    saved=work/'scratch/寄售经办留底'
    migration.reference(run,turn,variant,3,seed)
    if turn in (1,2):
        current,forms=combined(work,JUNE,audit.accounting(work,JUNE),audit.signed_tables(work))
    elif turn==3:
        shutil.copyfile(out/'consignment.csv',out/'frozen/consignment-06.csv')
        for period in ('0626','0630'):
            shutil.copytree(work/CABINET/period,saved/period,ignore=shutil.ignore_patterns('内部讨论.xlsx'))
        return
    elif turn==5:
        with TemporaryDirectory() as tmp:
            union=Path(tmp)
            data=union/'input/财务共享'
            for name in ('收文登记','流转','寄售'):
                shutil.copytree(work/'input/财务共享'/name,data/name)
            shutil.copytree(work/'scratch/六月经办留底',data,dirs_exist_ok=True)
            shutil.copytree(saved,union/CABINET,dirs_exist_ok=True)
            docs=audit.signed_tables(union)
            credit=migration.credit_evidence(work,docs)
            initial=migration.apply_credits(audit.accounting(union,JULY),credit,docs)
            current,forms=combined(union,JULY,initial,docs)
            june,_=combined(union,JUNE,audit.accounting(union,JUNE),docs)
        bridge,routes=audit.changes((Table(out/'frozen/2025-06.csv').rows,[],june[2]),current)
        audit.write_rows(out/'bridge.csv',basic.BRIDGE,bridge)
        audit.write_rows(out/'routing_changes.csv',basic.ROUTING,routes)
    else:
        return
    audit.write_rows(out/'current.csv',basic.LEDGER,current[0])
    audit.write_rows(out/'unclaimed.csv',basic.QUEUE,current[1])
    audit.write_rows(out/'consignment.csv',paper.FORM,forms)


def read_forms(table):
    if table.error or not set(paper.FORM.split(','))<=set(table.headers):
        return {}
    indexed=defaultdict(list)
    for row in table.rows:
        tickets=tuple(sorted(t.strip() for t in row['tickets'].split('|'))) if row['tickets'] else ()
        indexed[keyed(row)].append((row['status'],tickets))
    return dict(indexed)


def form_score(actual,expected,weight):
    wanted={keyed(r):(r['status'],tuple(sorted(filter(None,r['tickets'].split('|'))))) for r in expected}
    matched=identified=0
    for key,entries in actual.items():
        if key in wanted and len(entries)==1:
            status,tickets=entries[0]
            truth,correct_tickets=wanted[key]
            matched+=status==truth
            identified+=(status,tickets)==(truth,correct_tickets)
    denominator=len(wanted)+sum(len(v) for k,v in actual.items() if k not in wanted)
    return (weight*(matched+identified)/(2*denominator),weight,
            f'status {matched}/{denominator}, status with exact ticket membership {identified}/{denominator}')


def scale(scores,key,weight):
    points,old,reason=scores[key]
    scores[key]=weight*points/old,weight,reason


def score(run,variant,seed):
    cuts,forms=expected(seed)
    scores=audit.score(run,2,seed,cuts=cuts)
    snaps=run/'snapshots'
    for turn,label,weight in ((1,'initial',1),(2,'amended',2),(5,'current',2)):
        for measure in ('warehouse','invoices'):
            scale(scores,f'ledger.{label}.{measure}',2 if turn==5 else 1.5)
        if turn==2:
            scale(scores,'ledger.amended.exceptions',1)
        scores['ledger.consignment.'+label]=form_score(read_forms(Table(snaps/str(turn)/'consignment.csv')),
                                                        forms[turn],weight)
    validkeys={keyed(r) for r in forms[2]}
    frozen=read_forms(Table(snaps/'3/frozen/consignment-06.csv'))
    def valid_filing(entries):
        if len(entries)!=1:
            return False
        status,tickets=entries[0]
        if status=='BOOKED':
            return bool(tickets) and all(tickets) and len(tickets)==len(set(tickets))
        return status in ('MULTIPLE','CONFLICT') and not tickets
    valid=frozen.keys()==validkeys and all(valid_filing(entries) for entries in frozen.values())
    at_two=read_forms(Table(snaps/'2/consignment.csv'))
    retained=all(read_forms(Table(snaps/str(i)/'frozen/consignment-06.csv'))==frozen for i in range(4,10))
    for suffix,ok in (('reported',at_two==frozen),('retained',retained)):
        scale(scores,'ledger.freeze.'+suffix,1.5)
        scores['ledger.consignment.freeze.'+suffix]=(0.5 if valid and ok else 0,0.5,
                                                      'Compare actual per-bill filing across custody checkpoints')
    scale(scores,'ledger.bridge',1)
    scale(scores,'ledger.routing',2)
    credit=migration.checks(run,variant,3,seed)
    for source in ('receipt','invoice'):
        key='ledger.credit.'+source
        scores[key]=credit[key]
        scale(scores,key,1)
    return scores
