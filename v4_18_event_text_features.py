#!/usr/bin/env python3
"""Deterministic text features for V4.18-B event-cluster calibration.

This module is intentionally market-blind.  It has no dependency on prices,
returns, X02 labels, industry membership, or current concept constituents.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata

TEXT_FEATURE_VERSION = "v4.18-b.text.2"
SIMILARITY_METRIC = "binary_cosine_char_2_3gram_ascii_token"

# Formatting/legal boilerplate that adds no economic-context signal.
BOILERPLATE_PHRASES = (
    "股份有限公司",
    "有限责任公司",
    "有限公司",
    "关于",
    "公告",
    "的",
    "及",
)

# Routine filing patterns that cannot distinguish economic themes across issuers.
# These are governance/compliance templates, not market-moving event evidence.
_ROUTINE_RE = re.compile(
    r"股东(?:大)?会|董事会|监事会|独立董事|年度报告|季度报告|半年度报告|"
    r"审计报告|内部控制|述职报告|财务决算|权益分派|利润分配|"
    r"募集资金|监管协议|业绩说明会|投资者关系|会计政策|公司章程|"
    r"资金占用|关联资金往来|对外担保|提供担保|辞职|ESG报告|"
    r"信息披露管理|风险提示|日常经营|法律意见|回购注销|"
    r"独立意见|非经营性资金|内幕信息|短线交易|减持计划|持股变动",
    re.I,
)

# Economic action keywords that override routine wrappers.
_ACTIONS = (
    ("BUSINESS_CONTRACT", re.compile(r"中标|重大合同|销售合同|采购合同|供货合同|订单|定点通知")),
    ("CAPACITY_PROJECT", re.compile(r"投产|扩产|产能|生产基地|建设项目|投资建设")),
    ("PRODUCT_APPROVAL", re.compile(r"药品注册|临床试验|医疗器械注册|上市许可|产品认证")),
    ("CORPORATE_TRANSACTION", re.compile(r"收购|重大资产重组|控制权|资产出售|合并")),
    ("BUSINESS_COOPERATION", re.compile(r"战略合作|合作协议|合资")),
)

_CJK_OR_ASCII_RE = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9]+")
_NON_CONTENT_RE = re.compile(r"[^\u4e00-\u9fffa-z0-9]+")


def stable_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_title(title: object, stock_name: object = "") -> str:
    """Normalize a notice title without learning anything from a corpus."""
    text = unicodedata.normalize("NFKC", str(title or "")).lower().strip()
    issuer = unicodedata.normalize("NFKC", str(stock_name or "")).lower().strip()
    if issuer:
        text = text.replace(issuer, "")

    for phrase in BOILERPLATE_PHRASES:
        text = text.replace(phrase.lower(), "")

    # Remove punctuation/whitespace while preserving Chinese and ASCII content.
    text = _NON_CONTENT_RE.sub("", text)
    return text


def text_tokens(normalized_title: str) -> frozenset[str]:
    """Binary CJK 2/3-grams plus whole ASCII/alphanumeric terms."""
    tokens: set[str] = set()
    for match in _CJK_OR_ASCII_RE.finditer(normalized_title):
        chunk = match.group(0)
        if re.fullmatch(r"[a-z0-9]+", chunk):
            if len(chunk) >= 2:
                tokens.add(f"a:{chunk}")
            continue

        for n in (2, 3):
            if len(chunk) < n:
                continue
            for i in range(len(chunk) - n + 1):
                tokens.add(f"{n}:{chunk[i:i+n]}")
    return frozenset(tokens)


def binary_cosine(tokens_a: frozenset[str], tokens_b: frozenset[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    common = len(tokens_a.intersection(tokens_b))
    if common == 0:
        return 0.0
    return common / math.sqrt(len(tokens_a) * len(tokens_b))


def title_similarity(
    title_a: object,
    title_b: object,
    stock_name_a: object = "",
    stock_name_b: object = "",
) -> float:
    norm_a = normalize_title(title_a, stock_name_a)
    norm_b = normalize_title(title_b, stock_name_b)
    return binary_cosine(text_tokens(norm_a), text_tokens(norm_b))


def theme_eligible(title: object) -> bool:
    """Market-blind title eligibility: exclude routine governance filings.

    Routine filings (board resolutions, periodic reports, compliance notices)
    share identical templates across unrelated issuers, producing spurious
    high-similarity pairs that degrade clustering precision.

    Economic action titles (M&A, contracts, capacity projects) are always
    eligible even when wrapped in a routine template.
    """
    text = unicodedata.normalize("NFKC", str(title or "")).strip()
    text = re.sub(r"^[^:：]{1,32}[:：]", "", text)
    has_action = any(pat.search(text) for _, pat in _ACTIONS)
    if has_action:
        return True
    if _ROUTINE_RE.search(text):
        return False
    return True
