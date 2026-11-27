"""Offline reference CLI for the follow-on task. Never installed in a model worktree."""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def solve(directory, plan):
    events={}
    for p in sorted((directory/'packets').iterdir()):
        for row in map(json.loads,p.read_text().splitlines()):
            if row['day']<=plan['day'] and row['seq']<=plan['lanes'][row['lane']]:
                events.setdefault(row['eid'],row)
    rules=[]
    if (directory/'aliases.csv').exists():
        with (directory/'aliases.csv').open() as f: rules=list(csv.DictReader(f))
    def acct(row):
        for a in rules:
            if (a['tenant'],a['raw'])==(row['tenant'],row['ticket']) and int(a['start'])<=row['day']<=int(a['end']):
                return (row['tenant'],a['canon'])
        return (row['tenant'],row['ticket'])

    authority=(directory/'handover.txt').read_text().split('由 ')[-1].split()[0] if rules else ''
    decisions={}; paired=defaultdict(list); recalls=[]; postings=[]
    for r in events.values():
        if r['kind']=='leg':paired[r['tenant'],r['ref']].append(r)
        elif r['kind']=='recall':recalls.append(r)
        else:postings.append((r['day'],r['order'],[r]))
    groups={}
    for k,members in paired.items():
        members.sort(key=lambda r:r['units'])
        if len(members)==1: decisions[members[0]['eid']]='pending'
        elif len(members)!=2 or members[0]['units']>=0 or members[0]['units']!=-members[1]['units'] or acct(members[0])==acct(members[1]):
            decisions.update((m['eid'],'invalid') for m in members)
        else:
            groups[k]=(max(m['day'] for m in members),max(m['order'] for m in members),members)
    recalled=set()
    for r in sorted(recalls,key=lambda r:(r['day'],r['order'])):
        k=(r['tenant'],r['ref'])
        if k not in groups or r['signer']!=authority or r['day']<groups[k][0] or r['order']<=groups[k][1]: d='denied'
        elif k in recalled:d='duplicate'
        else:d='posted';recalled.add(k)
        decisions[r['eid']]=d
    for k,g in groups.items():
        if k in recalled:decisions.update((r['eid'],'void') for r in g[2])
        else:postings.append(g)
    balances=Counter(); parcels=defaultdict(list); spends=Counter(); moves=Counter()
    def take(k, qty):
        picked=[]; kept=[]
        for eid,lo,hi in sorted(parcels[k],key=lambda v:(events[v[0]]['day'],events[v[0]]['order'],v[1])):
            split=min(hi,lo+qty)
            if lo<split:picked.append((eid,lo,split));qty-=split-lo
            if split<hi:kept.append((eid,split,hi))
        parcels[k]=kept
        return picked
    def money(eid,lo,hi):return hi*events[eid].get('cents',0)//events[eid]['units']-lo*events[eid].get('cents',0)//events[eid]['units']
    for day,order,batch in sorted(postings,key=lambda g:g[:2]):
        r=batch[0]; key=acct(r); qty=abs(r['units'])
        if r['kind']=='credit':
            balances[key]+=qty
            parcels[key].append((r['eid'],0,qty))
        elif balances[key]<qty:
            for member in batch:decisions[member['eid']]='denied'
            continue
        else:
            balances[key]-=qty
            received=take(key,qty)
            if len(batch)==2:
                dest=acct(batch[1]);balances[dest]+=qty;parcels[dest].extend(received)
            target=spends if len(batch)==1 else moves
            for eid,lo,hi in received:
                target[r['eid'],eid,'n']+=hi-lo;target[r['eid'],eid,'c']+=money(eid,lo,hi)
        for member in batch:decisions[member['eid']]='posted'
    totals=Counter()
    for (t,k),v in balances.items():totals[t]+=v
    result=dict(accounts=[[*k,v] for k,v in balances.items()],audit=list(decisions.items()),totals=list(totals.items()))
    if (directory/'finance.txt').exists():
        remaining=Counter()
        for k,portions in parcels.items():
            for eid,lo,hi in portions:
                remaining[(*k,eid,'n')]+=hi-lo;remaining[(*k,eid,'c')]+=money(eid,lo,hi)
        def report(table):
            keys={k[:-1] for k in table}
            return [[*k,table[(*k,'n')],table[(*k,'c')]] for k in sorted(keys)]
        result.update(lots=report(remaining),usage=report(spends))
        if (directory/'transfer.txt').exists():result['travel']=report(moves)
    return result


if __name__=='__main__':
    import sys
    inp,plan,output=map(Path,sys.argv[1:])
    output.write_text(json.dumps(solve(inp,json.loads(plan.read_text())),ensure_ascii=False))
