import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish


class FakeGitHub:
    number = 7
    head = 'a' * 40
    def __init__(self):
        self.writes = []
        self.stale = False
        self.existing = []
        self.line_error = None
    def check_head(self):
        if self.stale:
            raise publish.Stale()
    def pages(self, path):
        return iter(self.existing if '/pulls/' in path else [])
    def write(self, method, path, payload):
        self.check_head()
        if '/pulls/' in path and self.line_error:
            raise publish.ApiError(self.line_error)
        self.writes.append((method, path, payload))


def payload(status='complete', comments=None, **kwargs):
    return {'status': status, 'comments': comments or [], **kwargs}


def comment(line=12):
    return {'path': 'src/A.java', 'start_line': line, 'end_line': line,
            'content': '问题', 'severity': 'high', 'category': 'bug'}


class Tests(unittest.TestCase):
    def parse(self, data, outcome='success'):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            return publish.parse_result(path, outcome)

    def test_coverage_and_budget_not_success(self):
        self.assertEqual(self.parse(payload())['status'], 'complete')
        self.assertEqual(self.parse(payload('partial', summary={'budget_exceeded': True}))['status'], 'partial')
        self.assertEqual(self.parse(payload(manifest={'coverage': {'failed': [{'classification': 'timeout'}]}}))['status'], 'partial')
        self.assertEqual(self.parse(payload(), 'failure')['status'], 'failed')
        self.assertEqual(self.parse(payload('skipped'))['status'], 'skipped')

    def test_inline_and_repeat_deduplication(self):
        gh = FakeGitHub()
        result = self.parse(payload(comments=[comment()]))
        self.assertEqual(publish.publish(gh, result, 'https://example.test'), 0)
        inline = gh.writes[0][2]['body']
        self.assertIn(publish.INLINE_MARKER, inline)
        gh.writes = []
        gh.existing = [{'body': inline, 'user': {'login': 'github-actions[bot]'}}]
        publish.publish(gh, self.parse(payload(comments=[comment()])), 'https://example.test')
        self.assertEqual(len(gh.writes), 1)
        self.assertIn('/issues/', gh.writes[0][1])

    def test_unpositioned_and_422_go_to_summary(self):
        for item, error in [(comment(0), None), (comment(), 422)]:
            gh = FakeGitHub()
            gh.line_error = error
            self.assertEqual(publish.publish(gh, self.parse(payload(comments=[item])), 'https://example.test'), 0)
            self.assertIn('src/A.java', gh.writes[-1][2]['body'])

    def test_publication_failure_is_partial(self):
        gh = FakeGitHub()
        gh.line_error = 403
        self.assertEqual(publish.publish(gh, self.parse(payload(comments=[comment()])), 'https://example.test'), 1)
        self.assertIn('部分完成', gh.writes[-1][2]['body'])

    def test_stale_rejected_before_writes(self):
        gh = FakeGitHub()
        gh.stale = True
        with self.assertRaises(publish.Stale):
            publish.publish(gh, self.parse(payload(comments=[comment()])), 'https://example.test')
        self.assertEqual(gh.writes, [])

    def test_api_uses_current_head_and_repo(self):
        gh = publish.GitHub('token', 'org/repo', 7, 'a' * 40)
        with patch.object(gh, 'request', return_value={'state': 'open', 'head': {'sha': 'b' * 40, 'repo': {'full_name': 'org/repo'}}, 'base': {'repo': {'full_name': 'org/repo'}}, 'author_association': 'MEMBER'}):
            with self.assertRaises(publish.Stale):
                gh.check_head()

    def test_api_accepts_member_fork_and_rejects_nonmember(self):
        gh = publish.GitHub('token', 'org/repo', 7, 'a' * 40)
        member_fork_pr = {
            'state': 'open',
            'head': {'sha': 'a' * 40, 'repo': {'full_name': 'member-fork/repo'}},
            'base': {'repo': {'full_name': 'org/repo'}},
            'author_association': 'MEMBER',
        }
        with patch.object(gh, 'request', return_value=member_fork_pr):
            gh.check_head()

        for association in ('COLLABORATOR', 'CONTRIBUTOR', 'NONE'):
            pr = {**member_fork_pr, 'author_association': association}
            with patch.object(gh, 'request', return_value=pr):
                with self.assertRaises(publish.Stale):
                    gh.check_head()


if __name__ == '__main__':
    unittest.main()
