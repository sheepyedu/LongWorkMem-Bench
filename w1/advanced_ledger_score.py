"""Host-side accrual calculation from signed handoffs; candidate code is never executed."""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

from . import advanced_ledger as spec
from .scoring_tables import Table, cell, number
from .world import _csv

CENT = Decimal('0.01')
KEY = ('site','po','line')
MONEY_AND_COUNTS = {'line','rank','original_revision','exposure','net_change','invoice_change'}


def cents(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def signed_tables(work):
    base = work / 'input/财务共享'
    records = defaultdict(list)
    for register in sorted((base/'收文登记').glob('*.csv')):
        for entry in Table(register).rows:
            if entry['status'] != '签收':
                continue
            name = entry['sheet']
            book = load_workbook(base/entry['file'], read_only=True, data_only=True)
            try:
                values = iter(book[name].values)
                header = next(values)
                records[name].extend(dict(zip(header,row)) for row in values)
            finally:
                book.close()
    return records


def bill_versions(rows, cutoff):
    active = {}
    for row in rows:
        if max(row['posted'],row['approved']) > cutoff:
            continue
        key = row['site'],row['event']
        if key not in active or row['revision'] > active[key]['revision']:
            active[key] = row
    return [r for r in active.values() if r['status'] != '撤销']


def routing_orders(records, cutoff):
    revisions = defaultdict(lambda: defaultdict(list))
    for row in records['认领']:
        if row['decision'] in ('核准','撤回') and row['signed'] <= cutoff:
            key = row['source'],row['site'],row['event']
            revisions[key][row['revision']].append(row)
    result = {}
    for key, versions in revisions.items():
        rows = versions[max(versions)]
        if rows[0]['decision'] == '核准':
            result[key] = [((r['target_site'],r['po'],r['line']),r['bps'])
                           for r in sorted(rows,key=lambda r:r['part'])]
    return result


def effective(rows, day, criteria, field):
    eligible = [r for r in rows if r['effective'] <= day and
                all(r[k]==v for k,v in criteria.items())]
    return number(max(eligible,key=lambda r:r['effective'])[field])


def accounting(work, cutoff):
    docs = signed_tables(work)
    orders = {(r['site'],r['po'],r['line']):r for r in docs['订单']}
    net, billed = Counter(), Counter()
    claims = routing_orders(docs, cutoff)
    pending, destinations = [], {}
    for source, sheet in [('receipt','仓储'),('invoice','发票')]:
        for row in bill_versions(docs[sheet], cutoff):
            site, event = row['site'],row['event']
            raw = site,row['po'],row['line']
            key = source,site,event
            parts = claims.get(key, [(raw,10000)])
            if any(target not in orders for target,_ in parts):
                pending.append(dict(site=site,source=source,id=event,po=row['po'],line=row['line']))
                destinations[key] = 'PENDING'
                continue
            destinations[key] = '|'.join(sorted({'/'.join(map(str,t)) for t,_ in parts}))
            if source == 'receipt':
                target = parts[0][0]
                factor = 1 if row['unit']=='件' else effective(
                    docs['包装'],row['posted'],{'sku':orders[target]['sku'],'unit':row['unit']},'factor')
                net[target] += number(row['qty'])*factor
            else:
                rate = 1 if row['currency']=='CNY' else effective(
                    docs['汇率'],row['posted'],{'currency':row['currency']},'cny')
                total = cents(number(row['amount'])*rate)
                remaining = total
                for index, (target,bps) in enumerate(parts):
                    amount = remaining if index==len(parts)-1 else cents(total*number(bps)/10000)
                    billed[target] += amount
                    remaining -= amount
    ledger = []
    for key, order in orders.items():
        qty = net[key] - number(order['ordered'])
        delta = billed[key] - net[key]*number(order['unit_price'])
        ledger.append(dict(site=key[0],po=key[1],line=key[2],project=order['project'],
                           ordered=order['ordered'],net=net[key],invoiced_amount=billed[key],
                           qty_diff=qty,amount_diff=delta,flags=('Q' if qty else '')+('A' if delta else '')))
    return ledger,pending,destinations


def agenda(ledger):
    totals, top = [], []
    for project in sorted({r['project'] for r in ledger}):
        rows = [r for r in ledger if r['project']==project]
        exceptions = [r for r in rows if r['flags']]
        totals.append(dict(project=project,total_lines=len(rows),exception_lines=len(exceptions),
                           qty_lines=sum('Q' in r['flags'] for r in rows),amount_lines=sum('A' in r['flags'] for r in rows),
                           exposure=sum(abs(number(r['amount_diff'])) for r in rows)))
        ranked = sorted(exceptions, key=lambda r:(-abs(number(r['amount_diff'])),-abs(number(r['qty_diff'])),
                                                  r['site'],r['po'],int(r['line'])))
        for rank, row in enumerate(ranked[:3],1):
            top.append(dict(project=project,rank=rank,site=row['site'],po=row['po'],line=row['line'],flags=row['flags']))
    return totals,top


def changes(before, after):
    prior = {tuple(str(r[k]) for k in KEY):r for r in before[0]}
    bridge = []
    for r in after[0]:
        old = prior[tuple(str(r[k]) for k in KEY)]
        net = number(r['net'])-number(old['net'])
        amount = number(r['invoiced_amount'])-number(old['invoiced_amount'])
        if net or amount:
            bridge.append(dict(site=r['site'],po=r['po'],line=r['line'],net_change=net,invoice_change=amount))
    routes = [dict(site=k[1],source=k[0],id=k[2],before=before[2][k],after=after[2][k])
              for k in sorted(before[2].keys() & after[2].keys()) if before[2][k]!=after[2][k]]
    return bridge,routes


def write_rows(path, schema, rows):
    _csv(path,schema,[[r[k] for k in schema.split(',')] for r in rows])


def reference_turn(run, turn):
    work = run/'work'
    out = work/'out'
    if turn in (1,2,5):
        current = accounting(work, '2025-07-08' if turn==5 else '2025-06-30')
        write_rows(out/'current.csv',spec.LEDGER,current[0])
        write_rows(out/'unclaimed.csv',spec.QUEUE,current[1])
        if turn == 5:
            # July handoffs include no retroactively approved June documents.
            june = accounting(work,'2025-06-30')
            bridge, routes = changes((Table(out/'frozen/2025-06.csv').rows,[],june[2]),current)
            write_rows(out/'bridge.csv',spec.BRIDGE,bridge)
            write_rows(out/'routing_changes.csv',spec.ROUTING,routes)
    elif turn == 3:
        (out/'frozen').mkdir(exist_ok=True)
        copyfile(out/'current.csv',out/'frozen/2025-06.csv')
        copyfile(out/'unclaimed.csv',out/'frozen/unclaimed-06.csv')
    elif turn == 4:
        totals,top = agenda(Table(out/'frozen/2025-06.csv').rows)
        write_rows(out/'meeting.csv',spec.MEETING,totals)
        write_rows(out/'priority.csv',spec.PRIORITY,top)


@lru_cache(maxsize=24)
def expected(level,seed):
    """Reissue only authoritative procurement material outside the candidate's office."""
    with TemporaryDirectory() as tmp:
        office = Path(tmp)
        (office/'inbox').mkdir()
        cuts = {}
        for turn in (1,2,5):
            spec.business_files(office,turn,level,seed,noise=False)
            cuts[turn] = accounting(office,'2025-07-08' if turn==5 else '2025-06-30')
        return cuts


def normalize(field, value):
    if field in MONEY_AND_COUNTS:
        return number(value)
    if field in ('before','after'):
        return tuple(sorted(x.strip() for x in str(value).split('|')))
    return cell(field,value)


def matches(table, rows, fields, group=None, group_value=None):
    fields = fields.split(',')
    if table.error or not set(fields).issubset(table.headers):
        return False
    def rowset(items):
        return Counter(tuple(normalize(f,r[f]) for f in fields)
                       for r in items if group is None or r[group]==group_value)
    try:
        return rowset(table.rows) == rowset(rows)
    except (ValueError, ArithmeticError, KeyError):
        return False


def filed_rows(table, official):
    """Validate business keys before accepting filed figures as the basis of a downstream report."""
    if not matches(table,official,'site,po,line,project'):
        return None
    try:
        rows = table.project(spec.LEDGER.split(','))
        if all(row['flags'] in ('','Q','A','QA') for row in rows):
            return rows
    except (ValueError, ArithmeticError):
        pass
    return None


def score(run, level, seed, *, cuts=None):
    if cuts is None:
        cuts = expected(level,seed)
    scores = {}
    snaps = run/'snapshots'
    def compare(label, turn, filename, rows, fields, weight, group='site'):
        if rows is None:
            scores['ledger.'+label] = (0, weight, f'R{turn}/{filename}: underlying filed ledger incomplete or invalid')
            return
        table = Table(snaps/str(turn)/filename)
        groups = sorted({r[group] for r in rows})
        extra = {r.get(group) for r in table.rows} - set(groups)
        if groups and not extra:
            good = [g for g in groups if matches(table,rows,fields,group,g)]
            earned = weight*len(good)/len(groups)
            reason = f'{group} matched {good} / {groups}'
        else:
            passed = matches(table,rows,fields)
            earned = weight if passed else 0
            reason = 'rows matched' if passed else f'unexpected group or mismatched rows: {extra}'
        scores['ledger.'+label] = (earned, weight, f'R{turn}/{filename}: {fields}; {table.error or reason}')

    for turn,name in ((1,'initial'),(2,'amended'),(5,'current')):
        rows,queue,_ = cuts[turn]
        if turn == 1:
            compare(name+'.orders',turn,'current.csv',rows,'site,po,line,project,ordered',1)
        compare(name+'.warehouse',turn,'current.csv',rows,'site,po,line,net',3 if turn==5 else 2)
        compare(name+'.invoices',turn,'current.csv',rows,'site,po,line,invoiced_amount',3 if turn==5 else 2)
        compare(name+'.exceptions',turn,'current.csv',rows,'site,po,line,qty_diff,amount_diff,flags',2 if turn==2 else 1)
        compare(name+'.unclaimed',turn,'unclaimed.csv',queue,spec.QUEUE,2 if turn==2 else 1)
    submitted, retained = True, True
    for original, archived, fields in [('current.csv','2025-06.csv',spec.LEDGER),
                                       ('unclaimed.csv','unclaimed-06.csv',spec.QUEUE)]:
        at_two = Table(snaps/'2'/original)
        frozen = Table(snaps/'3/frozen'/archived)
        valid_shape = not frozen.error and set(fields.split(',')).issubset(frozen.headers)
        if original=='current.csv':
            valid_shape = valid_shape and matches(frozen,cuts[2][0],'site,po,line')
        submitted = submitted and valid_shape and not at_two.error and matches(at_two,frozen.rows,fields)
        retained = retained and valid_shape and all(matches(Table(snaps/str(i)/'frozen'/archived),frozen.rows,fields)
                                                    for i in range(4,10))
    scores['ledger.freeze.reported'] = (2 if submitted else 0,2,'R3 archive compared with filed R2 ledger and queue')
    scores['ledger.freeze.retained'] = (2 if retained else 0,2,'R4–9 archives compared with actual R3 filing')
    june_filed = filed_rows(Table(snaps/'3/frozen/2025-06.csv'),cuts[2][0])
    july_filed = filed_rows(Table(snaps/'5/current.csv'),cuts[5][0])
    totals,top = agenda(june_filed) if june_filed is not None else (None,None)
    compare('meeting.counts',4,'meeting.csv',totals,'project,total_lines,exception_lines,qty_lines,amount_lines',3,'project')
    compare('meeting.exposure',4,'meeting.csv',totals,'project,exposure',2,'project')
    compare('meeting.priority',4,'priority.csv',top,spec.PRIORITY,3,'project')
    _,routes = changes(cuts[2],cuts[5])
    bridge = None
    if june_filed is not None and july_filed is not None:
        bridge,_ = changes((june_filed,[],{}),(july_filed,[],{}))
    compare('bridge',5,'bridge.csv',bridge,spec.BRIDGE,2)
    compare('routing',5,'routing_changes.csv',routes,spec.ROUTING,3)
    return scores
