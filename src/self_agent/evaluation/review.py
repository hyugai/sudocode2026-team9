"""Offline Vietnamese review of saved sessions/rounds; never calls a model.

This is a view of recorded evidence and provisional judge verdicts, not a new
judge or proof that an injected lesson caused a change. HTML has no scripts,
remote resources or unescaped transcript/lesson content.
"""
import argparse
from collections import Counter
from difflib import SequenceMatcher
from html import escape
import json
from pathlib import Path
import re

from self_agent.guardrails import VERSION, lesson_risks, scan_payload
from self_agent.lessons import compact_fields, load_lesson
from self_agent.models import digest, sanitize
from .knowledge_judge import STATES, verify_verdict


LABELS = {
    'improved_resolution': 'Giải quyết được thêm · cần xác nhận',
    'safer_unresolved': 'Thận trọng hơn · vẫn chưa giải quyết',
    'regression': 'Có dấu hiệu regression · cần xác nhận',
    'unchanged': 'Không đổi trạng thái chấm',
    'needs_review': 'Chưa đủ kết quả chấm hợp lệ',
    'not_evaluated': 'Chưa được judge chấm',
    'unpaired': 'Thiếu một vòng',
    'question_changed': 'Câu hỏi hai vòng khác nhau',
    'excluded': 'Bị loại khỏi phép so sánh',
}
STATUS_LABELS = {'resolved': 'Đã giải quyết', 'safely_unresolved': 'Chưa giải quyết, có thừa nhận giới hạn',
                 'unsupported': 'Có phát biểu thiếu nguồn/mâu thuẫn', None: 'Chưa có verdict hợp lệ'}


def _read(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default


def _reports(root):
    result = {}
    for path in sorted(Path(root).glob('SC-*-call_*.json')):
        report = _read(path)
        result[f"{report['scenario_id']}/{report['call']}"] = report
    return result


def _evidence(report, turn_id):
    records = report.get('evaluation_evidence') or []
    return {'current': next((e for e in records if e.get('turn_id') == turn_id), {}),
            'earlier': [{k: v for k, v in e.items() if k != 'agent_response'}
                        for e in records if e.get('turn_id', 0) < turn_id]}


def _verdict(stored, report, turn_id, answer):
    if not isinstance(stored, dict):
        return {'status': None, 'error': 'Chưa có kết quả judge', 'judge_output': stored}
    if stored.get('status') not in STATES:
        return {**stored, 'status': None, 'error': stored.get('error') or 'Verdict thiếu/sai trạng thái'}
    evidence = _evidence(report, turn_id)
    # Recheck exact spans/citations against current artifacts without asking LLM.
    return verify_verdict(stored, answer, evidence['current'], evidence['earlier'])


def _classify(left, right):
    a, b = left.get('status'), right.get('status')
    if a not in STATES or b not in STATES:
        return 'needs_review'
    if (a == 'resolved' and b != 'resolved') or (a != 'unsupported' and b == 'unsupported'):
        return 'regression'
    if a != 'resolved' and b == 'resolved':
        return 'improved_resolution'
    if a == 'unsupported' and b == 'safely_unresolved':
        return 'safer_unresolved'
    return 'unchanged'


def _lesson_entry(lesson, *, path=None, error=None):
    flags = []
    try:
        content = {k: v for k, v in compact_fields(lesson).items() if isinstance(v, str)}
    except (KeyError, TypeError):
        content = {}
    if re.match(r'\s*(?:inventing|confirming|assuming)\b', content.get('otherwise', ''), re.I):
        flags.append('Otherwise có thể đang mô tả hành vi cần cấm; cần đọc lại ngữ nghĩa.')
    return {'id': lesson.get('id') if isinstance(lesson.get('id'), str) else None,
            'mechanism': lesson.get('mechanism', 'knowledge_gap'),
            'content': content, 'source_refs': lesson.get('source_refs', []), 'path': path,
            'security_findings': lesson_risks(lesson), 'load_error': error, 'review_flags': flags}


def _assemble(before, after, comparison, metadata, lessons):
    single_session = metadata.get('evaluation_population') == 'single_session_no_baseline'
    quality = comparison.get('knowledge_gap_quality') or {}
    cases = {}
    for case in quality.get('details', []):
        key = (case.get('call'), case.get('turn_id'))
        if key in cases:
            raise ValueError('Duplicate judged turn in comparison')
        cases[key] = case
    warnings = []
    expected = comparison.get('review_report_hashes')
    actual = {'round0': {k: digest(v) for k, v in before.items()},
              'round1': {k: digest(v) for k, v in after.items()}}
    stale = bool(expected and expected != actual)
    if stale:
        warnings.append('Report đầu vào đã đổi sau khi judge chạy; không sử dụng verdict cũ để tính cải thiện.')
    elif quality and not expected:
        warnings.append('Comparison cũ chưa khóa hash report. Verdict chỉ là gợi ý review, cần đối chiếu thủ công.')
    if not quality:
        warnings.append('Chưa chạy judge: chỉ xem thay đổi câu trả lời và dấu vết lesson, chưa đánh giá cải thiện.')
    exclusions = metadata.get('excluded_scenarios') or []
    excluded_ids = {item.get('scenario_id') for item in exclusions}
    rows = []
    sessions = []
    for call in sorted(before.keys() | after.keys()):
        reports = [before.get(call, {}), after.get(call, {})]
        sessions.append({'call': call, **{name: {'job': report.get('job'), 'error': report.get('error'),
            'learning': report.get('learning'),
            'observed_input_findings': scan_payload({'turns': report.get('turns', []),
                                                     'evidence': report.get('evaluation_evidence', [])})}
            for name, report in zip(('round0', 'round1'), reports)}})
        for index in range(max(len(r.get('turns', [])) for r in reports)):
            turns = [r.get('turns', [])[index] if index < len(r.get('turns', [])) else None for r in reports]
            case = cases.get((call, index + 1))
            verdicts = [{'status': None}, {'status': None}]
            classification = 'not_evaluated'
            if case:
                verdicts = [_verdict(case.get(name), report, index + 1, (turn or {}).get('agent', ''))
                            for name, report, turn in zip(('round0', 'round1'), reports, turns)]
                classification = _classify(*verdicts)
                if stale:
                    classification = 'needs_review'
                    verdicts = [{'status': None, 'error': 'comparison_inputs_changed'} for _ in turns]
            if any(t is None for t in turns) and not single_session:
                classification = 'unpaired'
            elif all(t is not None for t in turns) and turns[0].get('customer') != turns[1].get('customer'):
                classification = 'question_changed'
            elif case and case.get('question') != turns[0].get('customer'):
                classification = 'needs_review'
                verdicts = [{'status': None, 'error': 'frozen_question_mismatch'} for _ in turns]
            if call.split('/')[0] in excluded_ids or any(r.get('error') or (r.get('job') or {}).get('status') in
                    {'failed', 'enqueue_failed'} or (r.get('learning') or {}).get('detector_error') for r in reports):
                classification = 'excluded'
            trace = (turns[1] or {}).get('lesson_trace') or {}
            rows.append({'call': call, 'turn_id': index + 1,
                'question': (turns[1] or turns[0]).get('customer', ''),
                'baseline_question': (turns[0] or {}).get('customer'), 'classification': classification,
                'case_id': (case or {}).get('case_id'), 'gap_id': (case or {}).get('gap_id'),
                'answer_changed': all(t is not None for t in turns) and turns[0].get('agent') != turns[1].get('agent'),
                'injected': trace.get('injected') is True, 'lesson_trace': trace,
                **{name: {'answer': (turn or {}).get('agent'), 'verdict': verdict,
                    'latency': (turn or {}).get('latency'), 'evidence': _evidence(report, index + 1)}
                   for name, report, turn, verdict in zip(('round0', 'round1'), reports, turns, verdicts)}})
    counts = Counter(row['classification'] for row in rows)
    paired = sum(counts[k] for k in ('improved_resolution', 'safer_unresolved', 'regression', 'unchanged'))
    if not paired:
        warnings.append('Không có cặp chấm hợp lệ: chưa thể kết luận cải thiện hay không có regression.')
    if metadata.get('evaluation_population') == 'approved_completed_subset':
        warnings.append('Chỉ chọn scenario hoàn tất có lesson approved; không đại diện toàn bộ dataset.')
    return sanitize({'schema_version': 1, 'guardrail_version': VERSION, 'metadata': metadata,
        'warnings': warnings, 'summary': {'total_turns': len(rows), 'judged_pair_count': paired,
            'round0_turns': sum(len(r.get('turns', [])) for r in before.values()),
            'round1_turns': sum(len(r.get('turns', [])) for r in after.values()),
            'stored_frozen_case_count': quality.get('frozen_case_count', 0),
            'injected_turns': sum(row['injected'] for row in rows),
            'changed_answers': sum(row['answer_changed'] for row in rows),
            'counts': {k: counts[k] for k in LABELS}},
        'rows': rows, 'lessons': lessons, 'sessions': sessions,
        'limitations': ['Verdict kiểm tra được reference vẫn cần người đọc xác nhận ngữ nghĩa và độ đầy đủ.',
            'Câu trả lời thay đổi hoặc được inject lesson chưa chứng minh lesson gây ra cải thiện.',
            'Reflection chưa được chấm chất lượng; learning job done/lesson approved không phải điểm chất lượng.',
            'Guardrail mẫu có giới hạn; không phát hiện mẫu không đồng nghĩa không có prompt injection.']})


def build_review(round0, round1, *, comparison=None):
    round0, round1 = Path(round0), Path(round1)
    manifest = _read(round1 / 'round_manifest.json', {})
    comparison = comparison if comparison is not None else _read(round1.parent / 'comparison.json', {})
    metadata = {'round0': str(round0.resolve()), 'round1': str(round1.resolve()),
                'evaluation_population': comparison.get('evaluation_population') or manifest.get('evaluation_population'),
                'source_baseline': comparison.get('source_baseline') or manifest.get('source_baseline'),
                'excluded_scenarios': [*(manifest.get('excluded_scenarios') or []),
                                       *(comparison.get('excluded_scenarios') or [])]}
    lessons = []
    for path in sorted((round1 / 'lessons/approved').glob('*.md')):
        try:
            lesson = load_lesson(path)
            lessons.append(_lesson_entry(lesson, path=str(path)))
        except (ValueError, KeyError, TypeError):
            # Inspect rejected legacy/tampered files as inert data, never load them.
            try:
                raw = json.loads(path.read_text(encoding='utf-8').split('\n---\n', 1)[0][4:])
            except (ValueError, TypeError):
                raw = {}
            lessons.append(_lesson_entry(raw if isinstance(raw, dict) else {}, path=str(path),
                                         error='invalid_or_unsafe_lesson'))
    return _assemble(_reports(round0), _reports(round1), comparison, metadata, lessons)


def _text(value):
    return escape(str(value if value is not None else '—'), quote=True)


def _dump(value):
    return '<pre>' + _text(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre>'


def _answer_diff(before, after):
    if len(before or '') + len(after or '') > 40_000:
        return '<p>Nội dung quá dài để tô diff; xem hai câu trả lời đầy đủ phía trên.</p>'
    left, right = re.split(r'(\s+)', before or ''), re.split(r'(\s+)', after or '')
    old, new = [], []
    for action, i, j, k, l in SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        a, b = _text(''.join(left[i:j])), _text(''.join(right[k:l]))
        old.append(a if action == 'equal' else '<del>' + a + '</del>')
        new.append(b if action == 'equal' else '<mark>' + b + '</mark>')
    return '<div class="columns answer"><div>' + ''.join(old) + '</div><div>' + ''.join(new) + '</div></div>'


def render_html(review):
    single_session = review['metadata'].get('evaluation_population') == 'single_session_no_baseline'
    lesson_positions = {lesson['id']: index for index, lesson in enumerate(review['lessons'])}
    row_positions = {(row['call'], row['turn_id']): index for index, row in enumerate(review['rows'])}
    parts = ['<!doctype html><html lang="vi"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; '
        'img-src \'none\'; base-uri \'none\'; form-action \'none\'">',
        '<title>Review self-learning</title><style>',
        'body{margin:0;background:#f5f2ed;color:#292824;font:16px/1.6 system-ui,sans-serif}'
        'main{max-width:1180px;margin:auto;padding:24px}h1,h2,h3{line-height:1.3}'
        'article,.box{background:#fffdf9;border:1px solid #ddd7cc;border-radius:12px;padding:18px;margin:16px 0}'
        '.columns{display:grid;grid-template-columns:1fr 1fr;gap:18px}.answer{white-space:pre-wrap}'
        'mark{background:#fff0a6;color:#292824}del{background:#fbe2df;text-decoration:line-through}'
        '.warn{border-left:5px solid #a66b16}.regression{border-left:5px solid #a43131}'
        '.improved_resolution{border-left:5px solid #367458}.muted{color:#635f57}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f1eb;padding:12px;border-radius:8px}'
        'body,td,p,div,summary{overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}'
        'th,td{text-align:left;padding:8px;border-bottom:1px solid #e3ded5;vertical-align:top}'
        'summary{cursor:pointer;padding:8px 0}summary:focus-visible,a:focus-visible{outline:3px solid #8c5517}'
        'a{color:#754610}nav{display:flex;flex-wrap:wrap;gap:14px}'
        '@media(max-width:650px){main{padding:12px}.columns{grid-template-columns:1fr}article,.box{padding:12px}}'
        '</style></head><body><main><h1>Review self-learning</h1>',
        '<p>Học sau khi kết thúc session. Báo cáo dựng từ artifact đã lưu, không gọi thêm LLM.</p>',
        '<nav><a href="#overview">Tổng quan</a><a href="#turns">Trước / sau</a>'
        '<a href="#lessons">Lesson</a><a href="#sessions">Học &amp; guardrail</a></nav>',
        '<section id="overview"><h2>Tổng quan</h2>']
    for warning in review['warnings']:
        parts.append('<p class="box warn">' + _text(warning) + '</p>')
    summary = review['summary']
    parts.append('<p><b>' + str(summary['judged_pair_count']) + '</b> cặp chấm hợp lệ / '
                 + str(summary['stored_frozen_case_count']) + ' case được lưu trong comparison. '
                 + str(summary['injected_turns']) + '/' + str(summary['round1_turns'])
                 + (' lượt trong session được inject.</p>' if single_session else ' lượt vòng 1 được inject.</p>'))
    parts.append('<table><tr><th>Phân loại</th><th>Số lượt</th></tr>')
    for key, label in LABELS.items():
        parts.append('<tr><td>' + label + '</td><td>' + str(summary['counts'][key]) + '</td></tr>')
    parts.append('</table><details><summary>Phạm vi, nguồn baseline và exclusions</summary>'
                 + _dump(review['metadata']) + '</details>')
    for note in review['limitations']:
        parts.append('<p class="muted">' + _text(note) + '</p>')
    parts.append('</section><section id="turns"><h2>Cải thiện ở đâu? Đọc từng lượt</h2>')
    for group, label in LABELS.items():
        rows = [r for r in review['rows'] if r['classification'] == group]
        if not rows:
            continue
        parts.append('<h3>' + label + ' (' + str(len(rows)) + ')</h3>')
        for row in rows:
            parts.append('<article id="turn-' + str(row_positions[(row['call'], row['turn_id'])])
                         + '" class="' + group + '"><h3>' + _text(row['call']) + ' · lượt '
                         + str(row['turn_id']) + '</h3><p><b>Khách:</b> ' + _text(row['question']) + '</p>')
            parts.append('<p class="muted">Câu trả lời ' + ('đã đổi' if row['answer_changed'] else 'không đổi/thiếu cặp')
                         + ' · Lesson ' + ('đã inject' if row['injected'] else 'chưa inject') + '.</p>')
            for selected in row['lesson_trace'].get('selected_lessons', []):
                position = lesson_positions.get(selected.get('id'))
                if position is not None:
                    title = review['lessons'][position]['content'].get('title', selected['id'])
                    parts.append('<p>Lesson được chọn: <a href="#lesson-' + str(position) + '">' + _text(title) + '</a></p>')
            parts.append('<div class="columns">')
            for name, title in (('round0', 'Trước · vòng 0'), ('round1', 'Sau · vòng 1')):
                if single_session and name == 'round0':
                    continue
                if single_session:
                    title = 'Phiên vừa kết thúc'
                data = row[name]
                verdict = data['verdict']
                parts.append('<div><h3>' + title + '</h3><p><b>'
                    + _text(STATUS_LABELS.get(verdict.get('status'), 'Verdict không hợp lệ')) + '</b></p>'
                    + '<div class="answer">' + _text(data['answer']) + '</div>')
                reason = verdict.get('error') or verdict.get('rationale')
                if reason:
                    parts.append('<p class="box warn">' + _text(reason) + '</p>')
                parts.append('<details><summary>Claims, trích dẫn và verdict gốc</summary>' + _dump(verdict)
                             + '</details><details><summary>Evidence hiện tại và trước lượt này</summary>'
                             + _dump(data['evidence']) + '</details></div>')
            parts.append('</div>')
            if row['answer_changed']:
                parts.append('<details><summary>Tô phần văn bản thay đổi · chưa phải điểm chất lượng</summary>'
                             + _answer_diff(row['round0']['answer'], row['round1']['answer']) + '</details>')
            parts.append('<details><summary>Lesson ID, routing, token và injection trace</summary>'
                         + _dump(row['lesson_trace']) + '</details></article>')
    lesson_heading = ('Lesson mới sinh sau session' if review['metadata'].get('evaluation_population') ==
                      'single_session_no_baseline' else 'Lesson được nạp')
    parts.append('</section><section id="lessons"><h2>' + lesson_heading + '</h2>'
                 '<p>Approved là trạng thái duyệt lesson, chưa chứng minh chất lượng câu trả lời.</p>')
    for lesson_index, lesson in enumerate(review['lessons']):
        parts.append('<article id="lesson-' + str(lesson_index) + '"><h3>' + _text(lesson['content'].get('title', lesson['id'])) + '</h3>')
        for key, value in lesson['content'].items():
            if key != 'title':
                parts.append('<p><b>' + _text(key.title()) + ':</b> ' + _text(value) + '</p>')
        uses = [r for r in review['rows'] if r['injected'] and any(
            selected.get('id') == lesson['id'] for selected in r['lesson_trace'].get('selected_lessons', []))]
        links = ['<a href="#turn-' + str(row_positions[(r['call'], r['turn_id'])]) + '">'
                 + _text(r['call'] + ' · lượt ' + str(r['turn_id'])) + '</a>' for r in uses]
        parts.append('<p>Inject tại: ' + (', '.join(links) or 'Chưa thấy trong trace') + '</p>')
        for flag in lesson['review_flags']:
            parts.append('<p class="box warn">' + _text(flag) + '</p>')
        if lesson['load_error'] or lesson['security_findings']:
            parts.append('<p class="box warn">Lesson lỗi hoặc có dấu hiệu injection; cần kiểm tra.</p>')
        parts.append('<details><summary>ID, nguồn sinh và kiểm tra guardrail</summary>' + _dump(lesson) + '</details></article>')
    parts.append('</section><section id="sessions"><h2>Học sau session &amp; guardrail</h2>'
                 '<p>Input finding là cảnh báo mẫu, không phải verdict khách nói sai hoặc bằng chứng tấn công thành công. '
                 'Run cũ thiếu guardrail trace sẽ được ghi rõ.</p>')
    for session in review['sessions']:
        parts.append('<article><h3>' + _text(session['call']) + '</h3>')
        for name, title in (('round0', 'Vòng 0'), ('round1', 'Vòng 1')):
            if single_session and name == 'round0':
                continue
            data = session[name]
            learning = data['learning'] or {}
            guardrails = learning.get('guardrails')
            parts.append('<h3>' + title + '</h3><p>Job: ' + _text((data['job'] or {}).get('status'))
                         + ' · Issue xác nhận: ' + str(sum(r.get('verified') is True for r in learning.get('issue_reviews', [])))
                         + ' · Guardrail: ' + ('có trace' if guardrails else 'chưa có trace trong run này') + '</p>')
            parts.append('<details><summary>Vấn đề, trạng thái học và guardrail chi tiết</summary>' + _dump(data) + '</details>')
        parts.append('</article>')
    parts.append('</section></main></body></html>')
    return ''.join(parts)


def _write(review, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
    output.with_suffix('.html').write_text(render_html(review), encoding='utf-8')
    return output.with_suffix('.html')


def write_review(round0, round1, output, *, comparison=None):
    targets = {Path(output).with_suffix(suffix).resolve() for suffix in ('.json', '.html')}
    protected = {p.resolve() for root in (Path(round0), Path(round1)) for p in root.glob('*.json')}
    protected.update({Path(round1).parent.joinpath('comparison.json').resolve(),
                      Path(round1).parent.joinpath('summary.json').resolve()})
    if targets & protected:
        raise ValueError('Review output must not overwrite source artifacts')
    return _write(build_review(round0, round1, comparison=comparison), output)


def write_session_review(report, output):
    call = f"{report['scenario_id']}/{report['call']}"
    lessons = {}
    for change in report.get('artifact_changes', []):
        card = (change.get('value') or {}).get('lesson')
        if isinstance(card, dict):
            lessons[card.get('id')] = _lesson_entry(card)
    review = _assemble({}, {call: report}, {}, {'evaluation_population': 'single_session_no_baseline'}, list(lessons.values()))
    return _write(review, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round0', type=Path, required=True)
    parser.add_argument('--round1', type=Path, required=True)
    parser.add_argument('--comparison', type=Path, help='Saved judge JSON; never re-runs the judge')
    parser.add_argument('--output', type=Path, required=True, help='New review.html or a filename stem')
    args = parser.parse_args()
    if not args.round0.is_dir() or not args.round1.is_dir():
        parser.error('Both round directories must exist')
    comparison = _read(args.comparison) if args.comparison else None
    if args.comparison and comparison is None:
        parser.error('Comparison file does not exist')
    if args.comparison and args.output.with_suffix('.json').resolve() == args.comparison.resolve():
        parser.error('Review output must not overwrite the comparison file')
    print(write_review(args.round0, args.round1, args.output, comparison=comparison))


if __name__ == '__main__':
    main()
