#!/usr/bin/env python3
"""STEP SQL-FUNC stage 3 — independent gate over the rendered HTML.

Fails the run if the sheet quotes a SQL clause that does not exist in the
matching repo, cites an unresolvable file:line, claims a DB result that was
never run, or drops one of the mandated columns.

The important check is the first one: every functional rule printed in the
Old/New DB logic and Missing/changed columns is re-matched against the raw
source, so a parser bug cannot silently invent a filter or a join.

Usage:
    python3 gate_sql.py --new-root DIR --old-root DIR --html-glob 'PATTERN'
"""
import argparse
import glob
import json
import os
import re
import sys

ap = argparse.ArgumentParser()
ap.add_argument('--new-root', required=True)
ap.add_argument('--old-root', required=True)
ap.add_argument('--html-glob', required=True)
A = ap.parse_args()

SPEC = ['#', 'Method', 'What this API does', 'Expected behaviour (PRD)', 'PRD match',
        'Old source', 'Old request path', 'New request path', 'Old curl', 'New curl',
        'Status', 'Auth', 'Data input', 'Validation', 'Required inputs',
        'Co-dependent APIs', 'Controllers / GitHub', 'Use case',
        'Old DB logic (functional)', 'New DB logic (functional)', 'Logic match?',
        'Missing / changed in new', 'Tables missing in newdev', 'Tables new vs old',
        'DB data verified?']

matches = glob.glob(A.html_glob)
if not matches:
    sys.exit('no HTML matched %s' % A.html_glob)
# Newest by mtime: a timestamped name does not sort chronologically next to an
# older date-only name from a previous run.
path = max(matches, key=os.path.getmtime)
doc = open(path, encoding='utf-8').read()
errs = []

hdr = [h.replace('&amp;', '&').replace('&mdash;', '—')
       for h in re.findall(r'<th style="width:[^"]*">(.*?)</th>', doc)]
if hdr != SPEC:
    errs.append('HEADER mismatch\n   got:  %s\n   want: %s' % (hdr, SPEC))

m = re.search(r'<script>const DATA=(\{.*?\});\nconst ROWS', doc, re.S)
rows = json.loads(m.group(1))['rows']


def corpus(root):
    """Source text normalised the same way the extractor sees it.

    Queries are assembled from `"a" + "b"` fragments, so a reconstructed clause
    never appears verbatim in raw source; without collapsing the concatenation
    the gate would report thousands of false 'invented clause' hits.
    """
    buf = []
    for dp, _, fs in os.walk(os.path.join(root, 'src/main/java')):
        for f in fs:
            if f.endswith('.java'):
                buf.append(open(os.path.join(dp, f), encoding='utf-8',
                                errors='replace').read())
    t = '\n'.join(buf)
    t = re.sub(r'"\s*\+\s*"', '', t)
    return re.sub(r'\s+', ' ', t).lower()


NEWC, OLDC = corpus(A.new_root), corpus(A.old_root)


def squash(s):
    return re.sub(r'\s+', ' ', s).strip().lower()


# 1. Every quoted clause must exist verbatim in the corresponding repo.
CLAUSE = re.compile(
    r'^\s*•\s*(?:Reads from|Returns|Joins|Scoped by caller/resource|'
    r'Business filters|Grouped by|Having|Ordered by|Row limit):\s*(.+)$')
bad, checked = [], 0
for r in rows:
    for field, hay, side in (('old_logic', OLDC, 'OLD'), ('new_logic', NEWC, 'NEW')):
        for line in (r.get(field) or '').split('\n'):
            mm = CLAUSE.match(line)
            if not mm:
                continue
            body = re.sub(r'\s*…\s*\(\+\d+ more\)$', '', mm.group(1))
            # Verify each predicate/column separately: the cell re-joins list
            # items with ', ', so comparing the joined string would fail purely
            # on the source's original spacing.
            for frag in re.split(r'; |, ', body):
                frag = squash(frag).rstrip(' .…')
                if len(frag) < 8:
                    continue
                checked += 1
                if frag not in hay:
                    bad.append('%s %s: %s' % (side, r['verb'], frag[:110]))
if bad:
    errs.append('CLAUSE NOT FOUND IN SOURCE (%d of %d):\n   %s'
                % (len(bad), checked, '\n   '.join(bad[:8])))

# 2. Missing/changed cells must quote OLD text that exists in OLD.
gap_bad, gap_checked = [], 0
GAPLINE = re.compile(r'(?:ABSENT from NEW|OLD):\s*(.+?)(?:\s*\|\s*NEW\b|$)')
for r in rows:
    for line in (r.get('logic_missing') or '').split('\n'):
        mm = GAPLINE.search(line)
        if not mm:
            continue
        frag = squash(mm.group(1)).rstrip(' .…')
        if len(frag) < 8 or frag.startswith(('q', 'entire', 'nothing', 'none')):
            continue
        gap_checked += 1
        if frag not in OLDC:
            gap_bad.append('%s: %s' % (r['verb'], frag[:110]))
if gap_bad:
    errs.append('GAP QUOTES OLD TEXT NOT IN OLD REPO (%d of %d):\n   %s'
                % (len(gap_bad), gap_checked, '\n   '.join(gap_bad[:8])))

# 3. Citations resolve.
cite = re.compile(r'(src/main/java/[\w/]+\.java):(\d+)')
bad_cite, ncite = set(), 0
for r in rows:
    for field in ('old_logic', 'new_logic', 'logic_missing'):
        for f, ln in cite.findall(r.get(field) or ''):
            ncite += 1
            hit = [rt for rt in (A.old_root, A.new_root)
                   if os.path.exists(os.path.join(rt, f))]
            if not hit:
                bad_cite.add('missing file %s' % f)
                continue
            n = sum(1 for _ in open(os.path.join(hit[0], f), encoding='utf-8',
                                    errors='replace'))
            if int(ln) > n:
                bad_cite.add('%s:%s beyond EOF (%d lines)' % (f, ln, n))
if bad_cite:
    errs.append('BAD CITATIONS:\n   %s' % '\n   '.join(sorted(bad_cite)[:8]))

# 4. No row may claim a DB result, and no cell may be blank.
for r in rows:
    if not str(r.get('db_verified', '')).startswith('Not verified'):
        errs.append('db_verified claims a result but no DB was queried: %r'
                    % r.get('db_verified'))
        break
for r in rows:
    for k in ('use_case', 'logic_match', 'logic_match_cat', 'logic_missing',
              'tables_missing_newdev', 'tables_new_vs_old'):
        if not str(r.get(k, '')).strip():
            errs.append('EMPTY %s on %s %s'
                        % (k, r['verb'], r.get('new_path') or r.get('old_path')))
            break
    else:
        continue
    break

# 5. Table names must be real.
tbl = re.compile(r'^•\s*([A-Za-z_][\w.]*)$', re.M)
bad_tab, ntab = set(), 0
for r in rows:
    for field, hay in (('tables_missing_newdev', OLDC), ('tables_new_vs_old', NEWC)):
        for t in tbl.findall(r.get(field) or ''):
            ntab += 1
            if t.lower() not in hay and t.split('.')[-1].lower() not in hay:
                bad_tab.add('%s (%s)' % (t, field))
if bad_tab:
    errs.append('INVENTED TABLES:\n   %s' % '\n   '.join(sorted(bad_tab)[:10]))

if re.search(r'https://way\.com', doc):
    errs.append('apex https://way.com present in document')

print('file             :', path)
print('rows             :', len(rows))
print('clauses verified :', checked - len(bad), '/', checked)
print('gap quotes ok    :', gap_checked - len(gap_bad), '/', gap_checked)
print('citations ok     :', ncite - len(bad_cite), '/', ncite)
print('table names ok   :', ntab - len(bad_tab), '/', ntab)
print()
if errs:
    print('GATE FAIL (%d)' % len(errs))
    for e in errs[:10]:
        print(' -', e)
    sys.exit(1)
print('GATE PASS — every quoted clause found in source, all citations resolve, '
      'no DB claims')
