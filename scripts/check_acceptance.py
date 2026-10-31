#!/usr/bin/env python3
"""Validate TXT ledger dates, evidence, requirement coverage and plan fingerprint.

This checks record consistency only; it never changes status or proves a feature.
"""
import argparse
from collections import Counter
import datetime as dt
import hashlib
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STATUSES = {'未開始','設計完成','實作中','待驗證','部分通過','隔離通過','待確認'}
FIELDS = {'規劃節','驗收要求','狀態','核對日期','最後處理日期','最近驗證日期','範圍內完成日期','證據','缺口／下一步'}


def validate(root, as_of):
    ledger = (root/'docs/PAM_ACCEPTANCE.zh-TW.txt').read_text()
    fingerprint = hashlib.sha256((root/'docs/PAM_SYSTEM_PLAN.zh-TW.txt').read_bytes()).hexdigest()
    if '規劃 SHA-256：' + fingerprint not in ledger:
        raise ValueError('Plan changed: reconcile ledger coverage and update plan fingerprint')
    blocks = re.findall(r'^\[([A-Z0-9-]+)\]\n(.*?)(?=\n\[|\n四、)', ledger, re.M | re.S)
    result = {}
    for ident, block in blocks:
        if ident in result:
            raise ValueError('Duplicate acceptance ID: '+ident)
        fields = {}
        for line in block.strip().splitlines():
            key, value = line.split('：',1)
            if key in fields:
                raise ValueError('Duplicate field: '+ident)
            fields[key] = value
        if set(fields) != FIELDS or fields['狀態'] not in STATUSES:
            raise ValueError('Invalid fields/status: '+ident)
        dates = {}
        for field in ['核對日期','最後處理日期','最近驗證日期','範圍內完成日期']:
            value = fields[field]
            dates[field] = None if value == '—' else dt.date.fromisoformat(value)
            if dates[field] and dates[field] > as_of:
                raise ValueError('Future date: '+ident)
        if not dates['核對日期']:
            raise ValueError('Missing review date: '+ident)
        if fields['狀態'] == '未開始' and any(dates[k] for k in dates if k != '核對日期'):
            raise ValueError('Unstarted requirement has processing/completion date: '+ident)
        if fields['狀態'] in {'設計完成','實作中','部分通過','隔離通過'} and not dates['最後處理日期']:
            raise ValueError('Missing actual handling date: '+ident)
        if fields['狀態'] in {'部分通過','隔離通過'} and not dates['最近驗證日期']:
            raise ValueError('Missing verification date: '+ident)
        if fields['狀態'] == '隔離通過' and (not dates['範圍內完成日期'] or fields['證據'] == '—'):
            raise ValueError('Pass has no completion date/evidence: '+ident)
        if dates['範圍內完成日期'] and fields['狀態'] != '隔離通過':
            raise ValueError('Incomplete requirement has completion date: '+ident)
        if dates['範圍內完成日期'] and dates['範圍內完成日期'] > dates['最近驗證日期']:
            raise ValueError('Completion after last verification: '+ident)
        for evidence in fields['證據'].split('; '):
            if evidence == '—':
                continue
            path = (root/evidence).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError('Missing/unsafe evidence path: '+ident)
        if not fields['缺口／下一步']:
            raise ValueError('Missing remaining scope: '+ident)
        result[ident] = fields
    expected = {f'P{i:02d}' for i in range(8)} | set('ABCDEFGHIJKL') | {f'D{i:02d}' for i in range(1,11)}
    prefixes = [f'F{i:02d}-' for i in range(1,13)] + [f'G{i:02d}-' for i in range(1,6)]
    prefixes += [f'X{i}-' for i in range(17,23)] + ['B00-','R25-','R28-']
    if not expected <= set(result) or not all(any(i.startswith(prefix) for i in result) for prefix in prefixes):
        raise ValueError('Missing phase/gate/feature/core acceptance/decision coverage')
    counts = Counter(row['狀態'] for row in result.values())
    summary = '共 '+str(len(result))+' 項；'+'，'.join(k+' '+str(v) for k,v in sorted(counts.items()))+'。'
    if summary not in ledger:
        raise ValueError('Ledger summary is stale; update from per-item statuses')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--as-of', type=dt.date.fromisoformat,
                        default=dt.datetime.now(ZoneInfo('Asia/Taipei')).date())
    try:
        args = parser.parse_args()
        rows = validate(args.root, args.as_of)
        print('Acceptance ledger valid: '+str(len(rows))+' reviewed items; no status changed.')
    except (ValueError,OSError) as failure:
        print('Acceptance ledger invalid: '+str(failure),file=sys.stderr); sys.exit(1)
