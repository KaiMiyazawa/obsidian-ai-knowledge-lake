#!/usr/bin/env python3
"""Read-only session sources; resumable review ledger in a git-ignored directory."""
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

VERSION = 2
CHUNK_SIZE = 6000
PREFIXES = ('# AGENTS.md instructions', '<environment_context>', '<user_instructions>',
            '<turn_aborted>', '<local-command', '<command-name>', '<system-reminder>',
            '[Request interrupted', 'This session is being continued',
            'Generate a concise UI title', '<task-notification>')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.new')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)


def content_text(content):
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return '', ['unsupported message content']
    texts, unknown = [], []
    known = {'tool_use', 'tool_result', 'thinking', 'redacted_thinking', 'image',
             'input_image', 'output_image', 'input_audio', 'audio', 'document'}
    for block in content:
        if not isinstance(block, dict):
            unknown.append('non-object content block')
        elif block.get('type') in {'text', 'input_text', 'output_text'}:
            if isinstance(block.get('text'), str):
                texts.append(block['text'])
            else:
                unknown.append('non-string text block')
        elif block.get('type') not in known:
            unknown.append('unknown block: ' + str(block.get('type')))
    return '\n'.join(texts), unknown


def parse_source(path, provider):
    raw = path.read_bytes()
    turns, errors, excluded = [], [], Counter()
    source_id, cwd, title, formats = path.stem, '', '', set()
    assets = []
    try:
        decoded = raw.decode('utf-8')
    except UnicodeDecodeError:
        decoded = raw.decode('utf-8', errors='replace')
        errors.append({'line': 0, 'error': 'invalid UTF-8'})
    for line_no, line in enumerate(decoded.split('\n'), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            errors.append({'line': line_no, 'error': 'invalid JSON'})
            continue
        if not isinstance(row, dict):
            errors.append({'line': line_no, 'error': 'non-object record'})
            continue
        if provider == 'codex':
            p = row.get('payload', {})
            if row.get('type') == 'session_meta':
                source_id, cwd = p.get('id', source_id), p.get('cwd', cwd)
            if 'git' in row and 'instructions' in row:
                source_id = row.get('id', source_id)
            if row.get('type') == 'message':
                p = row
                formats.add('codex-legacy')
            elif row.get('type') == 'response_item' and p.get('type') == 'message':
                formats.add('codex-response-item')
            else:
                # Unknown records with dialogue-like fields must block completeness.
                if row.get('role') in ('user', 'assistant') and 'content' in row:
                    errors.append({'line': line_no, 'error': 'unhandled dialogue record'})
                continue
        else:
            source_id, cwd = row.get('sessionId', source_id), row.get('cwd', cwd)
            if row.get('type') == 'custom-title':
                title = row.get('customTitle', '')
            if row.get('type') not in ('user', 'assistant'):
                continue
            p = row.get('message', {})
            formats.add('claude-jsonl')
            if row.get('isMeta'):
                excluded['meta'] += 1
                continue
            # Do not silently drop isSidechain records from root sessions.
        role = p.get('role', row.get('type'))
        if role not in ('user', 'assistant'):
            continue
        content = p.get('content')
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') in ('image', 'input_image', 'output_image', 'document', 'audio', 'input_audio'):
                    assets.append({'line': line_no, 'type': block['type'], 'status': 'unreviewed'})
        text, problems = content_text(p.get('content'))
        errors.extend({'line': line_no, 'error': e} for e in problems)
        if text.startswith('<environment_context>') and not cwd:
            match = re.search(r'Current working directory: ([^\n]+)', text)
            if match:
                cwd = match[1]
        if role == 'user' and text.startswith(PREFIXES):
            excluded['injected_context'] += 1
            continue
        if not text.strip():
            excluded['non_text_message'] += 1
            continue
        turns.append({'id': str(line_no), 'role': role, 'time': row.get('timestamp', ''),
                      'text': text})
    return {'source_id': source_id, 'cwd': cwd, 'title': title,
            'sha256': digest(raw), 'bytes': len(raw), 'formats': sorted(formats),
            'errors': errors, 'excluded': dict(excluded), 'assets': assets, 'turns': turns}


def chunks_for(turns):
    """All dialogue text is covered; no keyword filtering or repeated-utterance deletion."""
    chunks, current, length = [], [], 0
    for turn in turns:
        for offset in range(0, len(turn['text']), CHUNK_SIZE):
            part = {**turn, 'offset': offset, 'text': turn['text'][offset:offset + CHUNK_SIZE]}
            if current and length + len(part['text']) > CHUNK_SIZE:
                chunks.append(current)
                current, length = [], 0
            current.append(part)
            length += len(part['text'])
    if current:
        chunks.append(current)
    return [{'id': digest(json.dumps(c, ensure_ascii=False, sort_keys=True).encode()),
             'parts': c} for c in chunks]


def scan(home, work):
    manifest_path = work / 'ledger.json'
    ledger = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'version': VERSION, 'sessions': {}}
    for entry in ledger['sessions'].values():
        entry['present'] = False
    roots = [('codex', home / '.codex/sessions'), ('codex', home / '.codex/archived_sessions'),
             ('claude', home / '.claude/projects')]
    for provider, root in roots:
        for path in sorted(root.rglob('*.jsonl')):
            if 'subagents' in path.parts:
                continue
            key = digest(str(path).encode())[:20]
            old = ledger['sessions'].get(key, {})
            raw_hash = digest(path.read_bytes())
            if old.get('parser_version') == VERSION and old.get('sha256') == raw_hash and (work / 'normalized' / (key + '.json')).exists():
                old['present'] = True
                continue
            parsed = parse_source(path, provider)
            chunks = chunks_for(parsed['turns'])
            old_reviews = old.get('reviews', {})
            reviews = {c['id']: old_reviews[c['id']] for c in chunks if c['id'] in old_reviews}
            pending = {c['id']: old['pending'][c['id']] for c in chunks if c['id'] in old.get('pending', {})}
            save(work / 'normalized' / (key + '.json'), {'turns': parsed.pop('turns'), 'chunks': chunks})
            ledger['sessions'][key] = {**parsed, 'provider': provider, 'source': str(path),
                                      'present': True, 'parser_version': VERSION, 'chunk_ids': [c['id'] for c in chunks],
                                      'reviews': reviews, 'pending': pending,
                                      'organization': old.get('organization', 'unchanged')}
    # Exact copies are annotations only: branch/common-prefix matches never auto-close a review.
    groups, prefixes = {}, {}
    for key, entry in ledger['sessions'].items():
        if not entry['present']:
            continue
        normalized = json.loads((work / 'normalized' / (key + '.json')).read_text())
        signature = digest(json.dumps([(t['role'], t['text']) for t in normalized['turns']], ensure_ascii=False).encode())
        entry['exact_dialogue_duplicate_of'] = groups.get(signature) if normalized['turns'] else None
        if normalized['turns']:
            groups.setdefault(signature, key)
        hashes = [digest((t['role'] + '\0' + t['text']).encode()) for t in normalized['turns']]
        entry['shared_prefix'] = None
        if hashes:
            best = (0, None)
            for other, previous in prefixes.get(hashes[0], []):
                count = 0
                for a, b in zip(hashes, previous):
                    if a != b:
                        break
                    count += 1
                if count > best[0]:
                    best = (count, other)
            if best[0] >= 2:
                entry['shared_prefix'] = {'session': best[1], 'turn_count': best[0], 'auto_skipped': False}
            prefixes.setdefault(hashes[0], []).append((key, hashes))
    save(manifest_path, ledger)
    return ledger


def summary(ledger):
    entries = list(ledger['sessions'].values())
    return {'files': len(entries), 'present': sum(e['present'] for e in entries),
            'missing_sources': sum(not e['present'] for e in entries),
            'parse_blocked': sum(bool(e['errors']) for e in entries),
            'no_dialogue_requires_inspection': sum(not e['chunk_ids'] for e in entries),
            'chunks': sum(len(e['chunk_ids']) for e in entries),
            'reviewed_chunks': sum(len(e['reviews']) for e in entries),
            'pending_chunks': sum(len(e.get('pending', {})) for e in entries),
            'sessions_with_unreviewed_assets': sum(bool(e.get('assets')) for e in entries),
            'text_review_complete': sum(bool(e['chunk_ids']) and not e['errors'] and e['present'] and
                                   len(e['reviews']) == len(e['chunk_ids']) for e in entries),
            'exact_duplicate_files': sum(bool(e.get('exact_dialogue_duplicate_of')) for e in entries)}


def packet(work, limit, session=None, order='shortest', include_pending=False):
    if limit < CHUNK_SIZE + 2000:
        raise ValueError('max-chars must be at least 8000')
    ledger = json.loads((work / 'ledger.json').read_text())
    items, used = [], 0
    def priority(kv):
        key, entry = kv
        stable = (entry['source_id'], key)
        if order == 'source':
            return stable
        remaining = sum(c not in entry['reviews'] and
                        (include_pending or session is not None or c not in entry.get('pending', {}))
                        for c in entry['chunk_ids'])
        return (remaining, entry['bytes'], *stable)

    for key, entry in sorted(ledger['sessions'].items(), key=priority):
        if session and key != session and entry['source_id'] != session:
            continue
        if not entry['present'] or entry['errors']:
            continue
        data = json.loads((work / 'normalized' / (key + '.json')).read_text())
        for index, chunk in enumerate(data['chunks']):
            if chunk['id'] in entry['reviews']:
                continue
            if not include_pending and not session and chunk['id'] in entry.get('pending', {}):
                continue
            item = {'session': key, 'source_id': entry['source_id'], 'provider': entry['provider'],
                    'source_hash': entry['sha256'], 'cwd': entry['cwd'],
                    'chunk_index': index, 'chunk_count': len(data['chunks']), 'chunk': chunk}
            size = len(json.dumps(item, ensure_ascii=False))
            if size > limit and not items:
                raise ValueError(f'chunk exceeds packet limit ({size} chars); increase --max-chars')
            if used + size > limit:
                save(work / 'packet.json', {'items': items, 'characters': used})
                return {'items': len(items), 'characters': used, 'path': str(work / 'packet.json')}
            items.append(item)
            used += size
    save(work / 'packet.json', {'items': items, 'characters': used})
    return {'items': len(items), 'characters': used, 'path': str(work / 'packet.json')}


def review(work, file, vault):
    ledger = json.loads((work / 'ledger.json').read_text())
    rows = json.loads(file.read_text())
    verified = {}

    def fingerprint(path):
        stat = path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def verified_digest(path):
        path = path.resolve()
        if path not in verified:
            before = fingerprint(path)
            value = digest(path.read_bytes())
            if fingerprint(path) != before:
                raise ValueError('file changed during review: ' + str(path))
            verified[path] = (before, value)
        return verified[path][1]

    for row in rows:
        entry = ledger['sessions'][row['session']]
        source = Path(entry['source'])
        if not source.exists() or verified_digest(source) != entry['sha256']:
            raise ValueError('source changed since scan; scan again')
        if row['source_hash'] != entry['sha256'] or row['chunk_id'] not in entry['chunk_ids']:
            raise ValueError('stale or unknown review; regenerate packet')
        if row['outcome'] not in ('no_durable_knowledge', 'already_saved', 'recovered', 'needs_context'):
            raise ValueError('invalid outcome')
        if not row.get('reason'):
            raise ValueError('review requires reason')
        if row['outcome'] in ('already_saved', 'recovered'):
            if not row.get('destinations') and not row.get('external_files'):
                raise ValueError('saved knowledge requires destinations')
            for destination in row.get('destinations', []):
                path = (vault / destination).resolve()
                if not path.is_relative_to(vault.resolve()) or not path.is_file():
                    raise ValueError('missing or external destination: ' + destination)
            for artifact in row.get('external_files', []):
                path = Path(artifact['path'])
                if not path.is_absolute() or not path.is_file():
                    raise ValueError('external file must exist at an absolute path')
                if verified_digest(path) != artifact.get('sha256'):
                    raise ValueError('external file changed or has no verified hash')
        if row['outcome'] == 'needs_context':
            # Pending findings remain in the queue until resolved.
            entry.setdefault('pending', {})[row['chunk_id']] = row
        else:
            entry.setdefault('pending', {}).pop(row['chunk_id'], None)
            entry['reviews'][row['chunk_id']] = row
    # Recheck all identities/metadata before committing; a cached hash must not
    # allow a source or evidence file modified during this batch to pass.
    for path, (before, _) in verified.items():
        if not path.is_file() or fingerprint(path) != before:
            raise ValueError('file changed during review: ' + str(path))
    save(work / 'ledger.json', ledger)
    return summary(ledger)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path('tmp/.ai-chat-recovery/v2'))
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('scan'); s.add_argument('--home', type=Path, default=Path.home())
    sub.add_parser('status')
    p = sub.add_parser('packet'); p.add_argument('--max-chars', type=int, default=12000); p.add_argument('--session')
    p.add_argument('--order', choices=('shortest', 'source'), default='shortest')
    p.add_argument('--include-pending', action='store_true')
    r = sub.add_parser('review'); r.add_argument('file', type=Path); r.add_argument('--vault', type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.command == 'scan':
        result = summary(scan(args.home, args.work))
    elif args.command == 'packet':
        result = packet(args.work, args.max_chars, args.session, args.order, args.include_pending)
    elif args.command == 'review':
        result = review(args.work, args.file, args.vault)
    else:
        result = summary(json.loads((args.work / 'ledger.json').read_text()))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
