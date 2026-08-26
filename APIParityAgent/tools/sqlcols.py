#!/usr/bin/env python3
"""STEP SQL-FUNC stage 2 — append the eight use-case / SQL / logic columns.

Every cell is derived from the static trace in sqltrace.json, which only
contains text read out of opened files. Where the trace did not reach a
repository the cell says UNKNOWN rather than guessing a table.

Usage:
    python3 sqlcols.py --new-ctx /ms-consumer --old-ctx /way-consumer \
                       [--rows rows.json] [--trace sqltrace.json]

Rewrites --rows in place, adding: use_case, old_sql, new_sql, newdev_status,
db_same, logic, missing_logic, func_match, sql_gap.
"""
import argparse
import json
import re

ap = argparse.ArgumentParser()
ap.add_argument('--new-ctx', required=True, help='NEW context-path prefix, e.g. /ms-consumer')
ap.add_argument('--old-ctx', required=True, help='OLD context-path prefix, e.g. /way-consumer')
ap.add_argument('--rows', default='rows.json')
ap.add_argument('--trace', default='sqltrace.json')
ARGS = ap.parse_args()

TRACE = json.load(open(ARGS.trace))
ROWS = json.load(open(ARGS.rows))
NEW_ALL = set(TRACE.pop('__new_all_tables__'))
NEW_ALL_BARE = {t.split('.')[-1].lower() for t in NEW_ALL}

NO_SQL = 'N/A — no SQL in this path'
UNOPENED = 'UNKNOWN — repo/SQL not opened'


def bare(t):
    return t.split('.')[-1].lower()


def key(side, path, ctx):
    if not path or path == '—':
        return None
    p = path[len(ctx):] if path.startswith(ctx) else path
    return '%s|%s|%s' % (side, VERB, p)


def cell_sql(tr):
    """Old/New SQL (tables) cell."""
    if tr is None:
        return '', 'absent'
    if tr['tables'] or tr['sql']:
        parts = []
        if tr['tables']:
            parts.append('Tables: ' + ', '.join(tr['tables']))
        for s in tr['sql'][:3]:
            loc = '%s:%d' % (s['file'], s['line']) if s['line'] else s['file']
            parts.append('%s — %s' % (loc, s['q'][:300]))
        if len(tr['sql']) > 3:
            parts.append('(+%d more queries on this path)' % (len(tr['sql']) - 3))
        return '\n'.join(parts), 'sql'
    if tr['entered'] and not tr['touched_repo']:
        via = ', '.join(tr['visited'][:4]) or 'handler only'
        return '%s (opened: %s)' % (NO_SQL, via), 'nosql'
    return UNOPENED, 'unknown'


def main():
    global VERB
    stats = {}
    for r in ROWS:
        VERB = r['verb']
        nk = key('new', r.get('new_path'), ARGS.new_ctx)
        ok = key('old', r.get('old_path'), ARGS.old_ctx)
        ntr = TRACE.get(nk) if nk else None
        otr = TRACE.get(ok) if ok else None

        new_sql, nstate = cell_sql(ntr)
        old_sql, ostate = cell_sql(otr)

        # ---- Use case -------------------------------------------------
        what = (r.get('what') or '').strip()
        prd = (r.get('prd_expected') or '').strip()
        caller = ('An authenticated app user'
                  if str(r.get('auth', '')).startswith('JWT')
                  else 'An unauthenticated client')
        if what and not what.startswith('UNKNOWN'):
            use_case = '%s calls %s to: %s' % (caller, r['verb'], what.rstrip('.') + '.')
        elif prd and not prd.startswith('UNKNOWN'):
            use_case = '%s calls %s. PRD: %s' % (caller, r['verb'], prd)
        else:
            use_case = 'UNKNOWN — no use case in handler javadoc or PRD'

        # ---- Newdev table status --------------------------------------
        otabs = otr['tables'] if otr else []
        ntabs = ntr['tables'] if ntr else []
        union = sorted(set(otabs) | set(ntabs))
        if not union:
            newdev = 'N/A — no SQL' if 'nosql' in (nstate, ostate) else \
                     'UNKNOWN — newdev DB not queried'
        else:
            lines = []
            for t in union:
                if bare(t) in NEW_ALL_BARE:
                    lines.append('%s — Present in NEW code' % t)
                else:
                    lines.append('%s — Absent from NEW code' % t)
            lines.append('(newdev DB not queried — code-level status only)')
            newdev = '\n'.join(lines)

        # ---- DB data same? --------------------------------------------
        if nstate == 'nosql' and ostate in ('nosql', 'absent'):
            db_same = 'N/A — no SQL'
        elif ostate == 'nosql' and nstate == 'absent':
            db_same = 'N/A — no SQL'
        elif 'unknown' in (nstate, ostate):
            db_same = 'UNKNOWN — SQL not opened'
        else:
            db_same = 'Not run — SELECT templates only; newdev DB not queried'

        # ---- Logic comparison + Missing logic in new -------------------
        na_side = r['status'] in ('Missing in new', 'New only')
        if na_side:
            logic = 'N/A — Missing in new or New only'
            # The endpoint exists on one side only, so "missing logic" is best
            # expressed as which OLD tables NEW code never references at all.
            gone = sorted(t for t in otabs if bare(t) not in NEW_ALL_BARE)
            if r['status'] == 'Missing in new' and otabs:
                oloc = ('%s:%d' % (otr['sql'][0]['file'], otr['sql'][0]['line'])
                        if otr and otr['sql'] else 'OLD')
                if gone:
                    missing = ('Endpoint absent from NEW. OLD tables no NEW code '
                               'references:\n' + '\n'.join(
                                   '%d. %s (OLD %s)' % (i, t, oloc)
                                   for i, t in enumerate(gone, 1)))
                else:
                    missing = ('Endpoint absent from NEW, but every OLD table it '
                               'uses is referenced elsewhere in NEW code (%s)'
                               % ', '.join(otabs))
            else:
                missing = 'N/A — Missing in new or New only'
        elif nstate == 'unknown' or ostate == 'unknown':
            logic = 'UNKNOWN — service not opened'
            missing = 'UNKNOWN — did not open both services'
        elif nstate == 'nosql' and ostate == 'nosql':
            logic = 'Same — neither side reaches SQL on this path'
            missing = 'None — both opened, no extra old rule found'
        else:
            ob, nb = {bare(t) for t in otabs}, {bare(t) for t in ntabs}
            only_old = sorted(t for t in otabs if bare(t) not in nb)
            only_new = sorted(t for t in ntabs if bare(t) not in ob)
            oloc = ('%s:%d' % (otr['sql'][0]['file'], otr['sql'][0]['line'])
                    if otr and otr['sql'] else (otr['visited'][0] if otr and otr['visited'] else 'OLD'))
            nloc = ('%s:%d' % (ntr['sql'][0]['file'], ntr['sql'][0]['line'])
                    if ntr and ntr['sql'] else (ntr['visited'][0] if ntr and ntr['visited'] else 'NEW'))
            if not only_old and not only_new:
                logic = 'Same — same tables reached (%s)' % (', '.join(otabs) or 'none')
            else:
                d = []
                if only_old:
                    d.append('OLD-only tables: ' + ', '.join(only_old))
                if only_new:
                    d.append('NEW-only tables: ' + ', '.join(only_new))
                logic = 'Different — %s vs %s. %s' % (oloc, nloc, '; '.join(d))
            if only_old:
                missing = '\n'.join(
                    '%d. NEW path does not read/write %s (OLD %s)' % (i, t, oloc)
                    for i, t in enumerate(only_old, 1))
            else:
                missing = 'None — both opened, no extra old rule found'

        # ---- Functional SQL match --------------------------------------
        if db_same.startswith('N/A'):
            fmatch = 'N/A — no SQL'
        elif na_side:
            if r['status'] == 'Missing in new' and otabs:
                fmatch = ('Blocked — table missing in new' if gone
                          else 'Different data or logic')
            elif not otabs and not ntabs:
                fmatch = 'UNKNOWN'
            else:
                fmatch = 'Different data or logic'
        elif logic.startswith('Different') or missing[0].isdigit():
            fmatch = 'Different data or logic'
        elif logic.startswith('UNKNOWN') or db_same.startswith('UNKNOWN'):
            fmatch = 'UNKNOWN'
        else:
            fmatch = 'UNKNOWN — logic Same, DB rows not compared'

        r.update(use_case=use_case, old_sql=old_sql, new_sql=new_sql,
                 newdev_status=newdev, db_same=db_same, logic=logic,
                 missing_logic=missing, func_match=fmatch)
        r['sql_gap'] = (fmatch.startswith('Different') or fmatch.startswith('Blocked')
                        or missing[0].isdigit() or missing.startswith('Endpoint absent'))
        stats[fmatch] = stats.get(fmatch, 0) + 1

    json.dump(ROWS, open(ARGS.rows, 'w'), indent=1)
    print('rows: %d   SQL/logic gap rows: %d' % (len(ROWS), sum(1 for r in ROWS if r['sql_gap'])))
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print('  %-42s %d' % (k, v))


if __name__ == '__main__':
    main()
