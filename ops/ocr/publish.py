#!/usr/bin/env python3
"""Publish OCR v1.12.11 output without executing or trusting PR content."""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MARKER = '<!-- cloudhouse-ocr-summary -->'
INLINE_MARKER = '<!-- cloudhouse-ocr-finding:'


class ApiError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(f'GitHub API returned HTTP {status}')


class Stale(Exception):
    pass


class GitHub:
    def __init__(self, token, repository, number, head):
        self.token, self.repo, self.number, self.head = token, repository, number, head
        self.base = f'https://api.github.com/repos/{repository}'

    def request(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={
            'Authorization': f'Bearer {self.token}', 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json',
            'User-Agent': 'cloudhouse-ocr-review',
        })
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise ApiError(exc.code) from exc

    def pages(self, path):
        for page in range(1, 101):
            sep = '&' if '?' in path else '?'
            result = self.request('GET', f'{path}{sep}per_page=100&page={page}')
            yield from result
            if len(result) < 100:
                return
        raise RuntimeError('GitHub pagination limit exceeded')

    def check_head(self):
        pr = self.request('GET', f'/pulls/{self.number}')
        head = pr.get('head') or {}
        base = pr.get('base') or {}
        head_repo = head.get('repo')
        base_repo = base.get('repo')
        if (pr.get('state') != 'open' or head.get('sha') != self.head
                or head_repo is None or base_repo is None
                or base_repo.get('full_name') != self.repo
                or pr.get('author_association') not in ('MEMBER', 'OWNER')):
            raise Stale('PR changed or no longer eligible; results discarded')

    def write(self, method, path, payload):
        self.check_head()
        return self.request(method, path, payload)


def parse_result(path, outcome):
    if outcome != 'success' or not path.is_file():
        return {'status': 'failed', 'comments': [], 'reason': 'OCR 执行失败或未生成结果，请查看 Actions 运行状态。'}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('comments'), list):
            raise ValueError('invalid result')
        status = data.get('status')
        manifest = data.get('manifest') or {}
        coverage = manifest.get('coverage') or {}
        failed = coverage.get('failed') or []
        waived = coverage.get('waived') or []
        budget = (data.get('summary') or {}).get('budget_exceeded', False)
        if status not in ('complete', 'success', 'skipped') or failed or waived or budget or data.get('warnings'):
            reason = f'状态 {status or "unknown"}；失败项 {len(failed)}，跳过/豁免项 {len(waived)}，预算耗尽 {"是" if budget else "否"}，警告 {len(data.get("warnings") or [])}。'
            return {'status': 'partial', 'comments': data['comments'], 'reason': reason}
        return {'status': status, 'comments': data['comments'], 'reason': '没有可审查的支持文件。' if status == 'skipped' else '审查完成。'}
    except (ValueError, OSError, TypeError, AttributeError):
        return {'status': 'failed', 'comments': [], 'reason': 'OCR 结果无法解析，请查看 Actions 运行状态。'}


def finding(comment):
    if not isinstance(comment, dict):
        return None
    path, content = comment.get('path'), comment.get('content')
    if not isinstance(path, str) or not path or not isinstance(content, str) or not content.strip():
        return None
    severity = str(comment.get('severity') or 'unknown')[:30]
    category = str(comment.get('category') or 'other')[:30]
    body = f'**[{severity} / {category}]** {content.strip()}'[:12000]
    start, end = comment.get('start_line'), comment.get('end_line')
    line = end if type(end) is int and end > 0 else start
    if type(line) is not int or line <= 0:
        line = None
    return path, line, body


def publish(gh, result, run_url):
    gh.check_head()
    previous = list(gh.pages(f'/pulls/{gh.number}/comments'))
    existing = {c.get('body', '') for c in previous if c.get('user', {}).get('login') == 'github-actions[bot]'}
    fallback, invalid, errors, posted = [], 0, 0, 0
    for raw in result['comments']:
        item = finding(raw)
        if item is None:
            invalid += 1
            continue
        path, line, text = item
        digest = hashlib.sha256(json.dumps([gh.head, path, line, text], ensure_ascii=False).encode()).hexdigest()
        marker = f'{INLINE_MARKER}{digest} -->'
        body = f'{text}\n\n{marker}'
        if any(marker in old for old in existing):
            continue
        if line is None or posted >= 30:
            fallback.append((path, text))
            continue
        try:
            gh.write('POST', f'/pulls/{gh.number}/comments', {
                'body': body, 'commit_id': gh.head, 'path': path, 'line': line, 'side': 'RIGHT',
            })
            existing.add(body)
            posted += 1
        except ApiError as exc:
            fallback.append((path, text))
            if exc.status != 422:
                errors += 1
    if invalid or errors or len(fallback) > 30:
        result['status'] = 'partial'
    status = {'complete': '完成', 'success': '完成', 'skipped': '跳过', 'partial': '部分完成', 'failed': '失败'}[result['status']]
    lines = [MARKER, '## OpenCodeReview 审查', '', f'**状态：{status}** · 提交 `{gh.head}`', '', result['reason'],
             f'发现 {len(result["comments"])} 项；无法解析 {invalid} 项；行内发布错误 {errors} 项。',
             f'[查看 Actions 运行]({run_url})']
    if fallback:
        lines += ['', '### 未能定位或未发布为行内评论的意见']
        for path, text in fallback[:30]:
            lines += ['', f'**{path[:500]}**', '', text]
        if len(fallback) > 30:
            lines += ['', f'另有 {len(fallback) - 30} 项未展示，请查看运行状态。']
    body = '\n'.join(lines)
    if len(body) > 60000:
        result['status'] = 'partial'
        body = body.replace(f'**状态：{status}**', '**状态：部分完成**', 1)[:59000] + '\n\n摘要过长，已截断；审查结果不完整。'
    summaries = list(gh.pages(f'/issues/{gh.number}/comments'))
    old = next((c for c in summaries if MARKER in c.get('body', '') and c.get('user', {}).get('login') == 'github-actions[bot]'), None)
    if old:
        gh.write('PATCH', f'/issues/comments/{old["id"]}', {'body': body})
    else:
        gh.write('POST', f'/issues/{gh.number}/comments', {'body': body})
    return 1 if result['status'] in ('partial', 'failed') or errors or invalid else 0


def main():
    env = os.environ
    gh = GitHub(env['GH_TOKEN'], env['GITHUB_REPOSITORY'], int(env['PR_NUMBER']), env['HEAD_SHA'])
    result = parse_result(Path(env['OCR_WORK']) / 'result.json', env['OCR_STEP_OUTCOME'])
    url = f"{env['GITHUB_SERVER_URL']}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    try:
        return publish(gh, result, url)
    except Stale as exc:
        print(str(exc))
        return 0
    except (ApiError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f'OCR publication failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
