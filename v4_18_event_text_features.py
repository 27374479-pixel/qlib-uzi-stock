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

TEXT_FEATURE_VERSION = "v4.18-b.text.1"
SIMILARITY_METRIC = "binary_cosine_char_2_3gram_ascii_token"

# Keep this deliberately small.  These are formatting/legal boilerplate, not an
# attempt to hand-code profitable event categories.
BOILERPLATE_PHRASES = (
    "股份有限公司",
    "有限责任公司",
    "有限公司",
    "关于",
    "公告",
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
