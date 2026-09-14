#!/usr/bin/env python3
"""Confirm an agenda with explicitly accepted vacant roles, preserving time validation."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
from build_agenda import build_agenda, render_markdown, is_unresolved

PENDING_PATTERNS = [
    r'role [a-z_]+ exists but its person is unresolved',
    r'backstage role [a-z_]+ has unresolved person',
    r'prepared speech \d+ has unresolved speaker',
    r'prepared speech \d+ requires an evaluator but the name is unresolved',
    r'impromptu exists but its host is unresolved',
    r'impromptu requires an evaluator but the name is unresolved',
    r'.+ is missing its responsible person',
]



def apply_shuwen_transitions(data, source_dir):
    """Use the accepted club timing convention unless this meeting overrides a gap."""
    data = deepcopy(data)
    preliminary, _, _ = build_agenda(data, source_dir=source_dir, facts_only=True)
    rows = preliminary.get('timeline', [])
    host_index = next((i for i, r in enumerate(rows) if r['id'] == 'toastmaster_opening'), None)
    if host_index is None:
        return data
    # Keep malformed input visible to the engine instead of coercing it away.
    if not isinstance(data.get('agenda_overrides', []), list):
        return data
    overrides = data.setdefault('agenda_overrides', [])
    for index, row in enumerate(rows):
        if row.get('transition_after_override') is not None:
            continue
        existing = next((o for o in overrides if isinstance(o, dict) and o.get('id') == row['id']), None)
        if existing is None:
            existing = {'id': row['id']}
            overrides.append(existing)
        existing['transition_after'] = 0 if index < host_index or index == len(rows) - 1 else 1
    return data


def prepare(data, source_dir, allow_pending=False):
    if data.get('simple_version'):
        raise ValueError('本入口接受完整 meeting 结构；简化输入先使用 run_agenda.py confirm')
    data = apply_shuwen_transitions(data, source_dir)
    result, errors, warnings = build_agenda(data, source_dir=source_dir, facts_only=True)
    pending = [e for e in errors if any(re.fullmatch(p, e) for p in PENDING_PATTERNS)]
    blocking = [e for e in errors if e not in pending or not allow_pending]
    if blocking:
        raise ValueError('; '.join(blocking))
    meta = result['computed']
    if meta.get('delta_minutes') != 0 or meta.get('duration_confirmation_required'):
        raise ValueError('时间必须先闭合并确认，不能通过允许待定跳过')
    if pending:
        meta['status'] = 'exact_with_pending'
        result['accepted_pending_roles'] = pending
    # A missing title stays visibly pending; project names are not invented titles.
    for index, speech in enumerate(data.get('prepared_speeches', []), 1):
        if is_unresolved(speech.get('title')):
            row = next(r for r in result['timeline'] if r['id'] == f'prepared_speech:{index}')
            row['details'].insert(0, '题目待定')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--allow-pending', action='store_true', help='Only after the user accepts vacant roles shown as 待定')
    args = parser.parse_args()
    try:
        result = prepare(json.loads(args.input.read_text()), args.input.resolve().parent, args.allow_pending)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        path = args.output_dir / 'agenda.computed.json'
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        (args.output_dir / 'agenda.md').write_text(render_markdown(result))
        print(json.dumps({'ok': True, 'facts_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                          'pending_roles_allowed': bool(result.get('accepted_pending_roles')),
                          'computed_json': str(path.resolve()), 'computed': result['computed']}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
