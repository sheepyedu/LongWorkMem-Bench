"""Host-only scorecard for the single-session W1 benchmark."""

from statistics import mean


# Each probe belongs to one checkpoint only. Within a checkpoint the listed
# business tests have equal weight, using their measured completion fractions.
PROCESS = (
    ("首批订单、收货、发票及待认领底稿", 3, "ledger.initial.orders ledger.initial.warehouse ledger.initial.invoices ledger.initial.exceptions ledger.initial.unclaimed ledger.consignment.initial"),
    ("六月补件与首询的真实投递", 4, "ledger.amended.exceptions ledger.amended.unclaimed mail4.r2_route mail4.r2_content"),
    ("定版六月实报件并移交有效人事索引", 3, "ledger.freeze.reported ledger.consignment.freeze.reported pay.archive_coverage pay.archive_employee pay.archive_contract"),
    ("按实际报送版生成会议简报与优先单", 3, "ledger.meeting.counts ledger.meeting.exposure ledger.meeting.priority"),
    ("解释跨期变动并向当日岗位续核", 4, "ledger.bridge ledger.routing mail4.r5_route mail4.r5_content"),
    ("按批复核准项目、金额并完成银行核验", 3, "pay.release_scope pay.released_pool mail4.r6_route mail4.r6_content"),
    ("核实有效双签调班单与待核工时", 3, "pay.joint_dispatch pay.pending_tickets"),
    ("向指定岗位提交正确的待审附件", 4, "mail4.review_routes mail4.review_data"),
    ("以真实回执登记最终包件并归档原件", 3, "mail4.receipts mail4.archive mail4.r2_record mail4.r5_record mail4.r6_record"),
)
OUTCOMES = (
    ("ledger", "六月报送和七月采购账正确且可追溯", 18,
     "ledger.amended.warehouse ledger.amended.invoices ledger.consignment.amended ledger.freeze.retained "
     "ledger.consignment.freeze.retained ledger.current.warehouse ledger.current.invoices ledger.current.exceptions "
     "ledger.current.unclaimed ledger.consignment.current ledger.credit.receipt ledger.credit.invoice"),
    ("pay", "个人实发、项目守恒及可重算的工资簿", 20,
     "pay.correct_rows pay.conserved_pools "
     "pay.workbook_baseline pay.workbook_edited_hours pay.workbook_edited_pools"),
    ("mail", "结清应付余额并按授权完成资金交接", 12,
     "mail4.recognized mail4.payable mail4.revised mail4.disposition mail4.authorization mail4.privacy"),
    ("reserve", "各办理日完整正确入账并保留历史分录", 20,
     "memory.r3.case memory.r5.case memory.r8.case memory.r9.case memory.retention"),
)


def summarize(checks, *, details=False):
    items = {}

    def add(code, category, title, points, probes):
        evidence = {key: checks[key] for key in probes.split()}
        ratio = mean(earned / maximum for earned, maximum, _ in evidence.values())
        items[code] = dict(department=category, title=title, earned=round(points * ratio, 6), max=points)
        if details:
            items[code]["evidence"] = {k: dict(earned=v[0], max=v[1], reason=v[2]) for k, v in evidence.items()}

    for turn, (title, points, probes) in enumerate(PROCESS, 1):
        add(f"round.{turn}", "process", title, points, probes)
    for code, title, points, probes in OUTCOMES:
        add(f"result.{code}", "outcome", title, points, probes)
    return items
