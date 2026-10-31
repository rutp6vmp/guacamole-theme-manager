"""Prevent stale plans, missing evidence and false completion dates in ledger."""
import datetime as dt
import importlib.util
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('ledger_check', ROOT/'scripts/check_acceptance.py')
ledger = importlib.util.module_from_spec(spec); spec.loader.exec_module(ledger)


class AcceptanceLedgerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.text = (ROOT/'docs/PAM_ACCEPTANCE.zh-TW.txt').read_text()
        self.as_of = max(dt.date.fromisoformat(value) for value in re.findall(
            r'^(?:核對日期|最後處理日期|最近驗證日期|範圍內完成日期)：(\d{4}-\d{2}-\d{2})$',self.text,re.M))
        for evidence in re.findall(r'^證據：(.*)$', self.text, re.M):
            for name in evidence.split('; '):
                if name != '—':
                    target = self.root/name; target.parent.mkdir(parents=True,exist_ok=True); target.touch()
        (self.root/'docs/PAM_SYSTEM_PLAN.zh-TW.txt').write_bytes((ROOT/'docs/PAM_SYSTEM_PLAN.zh-TW.txt').read_bytes())

    def validate(self, text=None):
        (self.root/'docs/PAM_ACCEPTANCE.zh-TW.txt').write_text(self.text if text is None else text)
        return ledger.validate(self.root, self.as_of)

    def test_current_ledger_and_required_coverage(self):
        self.assertGreaterEqual(len(self.validate()), 152)

    def test_changed_plan_requires_reconciliation(self):
        with (self.root/'docs/PAM_SYSTEM_PLAN.zh-TW.txt').open('a') as stream:
            stream.write('\nNew unreviewed requirement\n')
        with self.assertRaisesRegex(ValueError, 'Plan changed'):
            self.validate()

    def test_unstarted_cannot_have_completion_date(self):
        text = re.sub(r'(狀態：未開始\n核對日期：[^\n]+\n最後處理日期：)—', r'\g<1>'+self.as_of.isoformat(), self.text, count=1)
        with self.assertRaisesRegex(ValueError, 'Unstarted'):
            self.validate(text)

    def test_future_dates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Future date'):
            self.validate(re.sub(r'^核對日期：\d{4}-\d{2}-\d{2}$',
                '核對日期：'+(self.as_of+dt.timedelta(days=1)).isoformat(),self.text,count=1,flags=re.M))

    def test_pass_without_completion_date_is_rejected(self):
        text = re.sub(r'(狀態：隔離通過\n(?:[^\n]+\n){3}範圍內完成日期：)[^\n]+', r'\g<1>—', self.text, count=1)
        with self.assertRaisesRegex(ValueError, 'completion date/evidence'):
            self.validate(text)

    def test_missing_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing/unsafe evidence'):
            self.validate(self.text.replace('證據：docs/ARCHITECTURE.md', '證據：docs/nonexistent-proof.txt', 1))
