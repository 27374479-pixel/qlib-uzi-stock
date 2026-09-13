"""Text-only research candidate, NOT an approved theme classifier.

Route economically specific titles to body review; never equate an action
category (e.g. acquisition) with a common cross-company market theme.
"""
import re
import unicodedata

VERSION = 'event-context-routing-candidate.2'
ROUTINE = re.compile(
    r'股东(?:大)?会|董事会|监事会|独立董事|年度报告|季度报告|半年度报告|'
    r'审计报告|内部控制|述职报告|财务决算|权益分派|利润分配|'
    r'募集资金|监管协议|业绩说明会|投资者关系|会计政策|公司章程|'
    r'资金占用|关联资金往来|对外担保|提供担保|辞职|ESG报告', re.I)
ACTIONS = (
    ('BUSINESS_CONTRACT', r'中标|重大合同|销售合同|采购合同|供货合同|订单|定点通知'),
    ('CAPACITY_PROJECT', r'投产|扩产|产能|生产基地|建设项目|投资建设'),
    ('PRODUCT_APPROVAL', r'药品注册|临床试验|医疗器械注册|上市许可|产品认证'),
    ('CORPORATE_TRANSACTION', r'收购|重大资产重组|控制权|资产出售|合并'),
    ('BUSINESS_COOPERATION', r'战略合作|合作协议|合资'),
)


def route_title(title):
    text = unicodedata.normalize('NFKC', str(title or '')).strip()
    # Issuer/ticker prefix is presentation only, not economic evidence.
    text = re.sub(r'^[^:：]{1,32}[:：]', '', text)
    actions = [name for name, pattern in ACTIONS if re.search(pattern, text)]
    routine = bool(ROUTINE.search(text))
    if actions:
        status = 'BODY_REVIEW_REQUIRED'
        reason = 'action_in_routine_wrapper' if routine else 'economic_action_title'
    elif routine:
        status, reason = 'ROUTINE_TITLE', 'generic_filing_not_theme_evidence'
    else:
        status, reason = 'UNRESOLVED_TITLE', 'insufficient_title_evidence'
    return dict(routing_version=VERSION, routing_status=status, reason=reason,
                action_categories='|'.join(actions), theme_assignment_allowed=False)
