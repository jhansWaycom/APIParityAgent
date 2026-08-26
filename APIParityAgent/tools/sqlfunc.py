#!/usr/bin/env python3
"""STEP SQL-FUNC stage 2 — functional (not table-list) comparison of DB logic.

Decomposes every query on a handler's path into the rules it actually applies
(what it reads, what it joins on, every filter with its literal, how it is
scoped to the caller, ordering, limits, aggregation), pairs each OLD query with
its closest NEW counterpart, and reports precisely which rules the NEW side
does not implement.

Nothing is inferred from a method name. Every rule printed is a clause parsed
out of SQL text that sqltrace.py read from an opened @Query / native query, and
gate_sql.py re-verifies each one against the repo.

Usage:
    python3 sqlfunc.py --new-ctx /ms-consumer --old-ctx /way-consumer \
                       [--rows rows.json] [--trace sqltrace.json]
"""
import argparse
import json
import re

ap = argparse.ArgumentParser()
ap.add_argument('--new-ctx', required=True)
ap.add_argument('--old-ctx', required=True)
ap.add_argument('--rows', default='rows.json')
ap.add_argument('--trace', default='sqltrace.json')
ap.add_argument('--new-root', help='NEW module root; enables reading the '
                                   'legacy->new column mappings its javadoc documents')
A = ap.parse_args()

TRACE = json.load(open(A.trace))
ROWS = json.load(open(A.rows))
NEW_ALL = set(TRACE.pop('__new_all_tables__'))
NEW_ALL_BARE = {t.split('.')[-1].lower() for t in NEW_ALL}

NOT_VERIFIED = 'Not verified — no DB access this run'


# ---------------------------------------------------------------- parsing ---
def split_top(s, seps):
    """Split on separators that sit at paren depth 0."""
    out, depth, cur, i = [], 0, '', 0
    low = s.lower()
    instr, qch = False, None
    while i < len(s):
        c = s[i]
        # Parens inside a literal (e.g. a format string) must not move depth,
        # or the whole clause collapses into one unsplittable fragment.
        if instr:
            cur += c
            if c == qch:
                instr = False
            i += 1
            continue
        if c in '"\'':
            instr, qch = True, c
            cur += c
            i += 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        if depth == 0:
            for sep in seps:
                # A separator that already begins with a space carries its own
                # left boundary; demanding a non-alnum before it rejects every
                # `... = ?1 and ...`, leaving the WHERE clause unsplit.
                bounded = sep[0].isspace() or i == 0 or not low[i - 1].isalnum()
                if low.startswith(sep, i) and bounded:
                    end = i + len(sep)
                    if end >= len(s) or not low[end].isalnum():
                        out.append(cur)
                        cur = ''
                        i = end
                        break
            else:
                cur += c
                i += 1
                continue
            continue
        cur += c
        i += 1
    out.append(cur)
    return [x.strip() for x in out if x.strip()]


def norm(x):
    """Compare old and new predicates on meaning, not on incidental syntax.

    Aliases, bind-parameter style (?1 vs :userId) and case differ freely
    between the two codebases; the column, operator and literal do not.
    """
    x = re.sub(r'\s+', ' ', x).strip().rstrip(',')
    x = re.sub(r'(?<![\w.])[A-Za-z]\w{0,3}\.(?=[A-Za-z]\w*)', '', x)   # drop aliases
    x = re.sub(r':\w+|\?\d*|%s', '<param>', x)                         # bind params
    x = re.sub(r'\s*([=<>!]+|<>)\s*', r' \1 ', x)
    x = re.sub(r'\s+', ' ', x)
    return x.strip().lower()


def clause(q, name, stops):
    m = re.search(r'(?<![\w.])' + name + r'\s', q, re.I)
    if not m:
        return ''
    rest = q[m.end():]
    cut = len(rest)
    for s in stops:
        mm = re.search(r'(?<![\w.])' + s + r'(?![\w.])', rest, re.I)
        if mm:
            cut = min(cut, mm.start())
    return rest[:cut].strip()


TAIL = ['where', 'group by', 'having', 'order by', 'limit', 'union']


def decompose(q):
    """Turn one query into the set of functional rules it applies."""
    r = {'reads': [], 'from': [], 'joins': [], 'filters': [], 'scope': [],
         'order': '', 'limit': '', 'group': '', 'having': '', 'agg': [],
         'write': ''}
    ql = q.lower().lstrip()
    for verb in ('insert', 'update', 'delete'):
        if ql.startswith(verb):
            r['write'] = verb.upper()

    sel = clause(q, 'select', ['from'])
    if sel:
        cols = split_top(sel, [','])
        r['reads'] = [re.sub(r'\s+', ' ', c).strip() for c in cols]
        for c in cols:
            am = re.match(r'\s*(count|sum|avg|min|max|group_concat)\s*\(', c, re.I)
            if am:
                r['agg'].append(am.group(1).upper())

    frm = clause(q, 'from', TAIL)
    if frm:
        # JOIN keywords may appear with several qualifiers.
        parts = re.split(r'(?i)\s+(?:inner |left outer |left |right outer |right |cross |full )?join\s+', frm)
        r['from'] = [re.sub(r'\s+', ' ', parts[0]).strip()]
        for p in parts[1:]:
            on = re.split(r'(?i)(?<![\w.])on(?![\w.])', p, 1)
            tbl = re.sub(r'\s+', ' ', on[0]).strip()
            cond = re.sub(r'\s+', ' ', on[1]).strip() if len(on) > 1 else ''
            r['joins'].append((tbl, cond))

    wh = clause(q, 'where', ['group by', 'having', 'order by', 'limit', 'union'])
    if wh:
        for p in split_top(wh, [' and ']):
            p = p.strip()
            if not p:
                continue
            # A predicate bound to a method argument scopes the query to the
            # caller/resource; a literal predicate is a business filter.
            if re.search(r':\w+|\?\d*(?![\w])|%s', p):
                r['scope'].append(p)
            else:
                r['filters'].append(p)

    r['order'] = clause(q, 'order by', ['limit', 'union'])
    r['limit'] = clause(q, 'limit', ['union'])
    r['group'] = clause(q, 'group by', ['having', 'order by', 'limit', 'union'])
    r['having'] = clause(q, 'having', ['order by', 'limit', 'union'])
    return r


def tables_of(d):
    out = set()
    for t in d['from'] + [j[0] for j in d['joins']]:
        m = re.match(r'([A-Za-z_][\w.]*)', t)
        if m:
            out.add(m.group(1).lower())
    return out


def norm_col(c):
    """A returned column compares on its expression, not its alias.

    `DISTINCT x AS foo` and `x AS bar` are the same datum; keeping the alias
    would report a rename as a lost column.
    """
    c = re.sub(r'(?i)^\s*distinct\s+', '', c)
    c = re.sub(r'(?i)\s+as\s+[\w`"]+\s*$', '', c)
    return norm(c)


def cols_of(d):
    return {norm_col(c) for c in d['reads']}


def describe(d, q):
    """Plain-language rendering of the rules, quoting the real clauses."""
    L = []
    if d['write']:
        L.append('%s statement.' % d['write'])
    if d['from']:
        L.append('Reads from: %s' % ', '.join(d['from']))
    if d['reads'] and not d['write']:
        cols = d['reads']
        shown = ', '.join(cols[:8]) + (' … (+%d more)' % (len(cols) - 8) if len(cols) > 8 else '')
        L.append('Returns: %s' % shown)
    if d['agg']:
        L.append('Aggregates: %s' % ', '.join(sorted(set(d['agg']))))
    for tbl, cond in d['joins']:
        L.append('Joins %s%s' % (tbl, ' ON %s' % cond if cond else ''))
    if d['scope']:
        L.append('Scoped by caller/resource: %s' % '; '.join(d['scope']))
    if d['filters']:
        L.append('Business filters: %s' % '; '.join(d['filters']))
    if d['group']:
        L.append('Grouped by: %s' % d['group'])
    if d['having']:
        L.append('Having: %s' % d['having'])
    if d['order']:
        L.append('Ordered by: %s' % d['order'])
    if d['limit']:
        L.append('Row limit: %s' % d['limit'])
    if not L:
        L.append('Query text present but no recognisable clauses parsed.')
    return L


# ---------------------------------------------------------------- pairing ---
def score(a, b):
    ta, tb = tables_of(a), tables_of(b)
    tb_bare = {t.split('.')[-1] for t in tb}
    ta_bare = {t.split('.')[-1] for t in ta}
    s = 3 * len(ta_bare & tb_bare)
    ca, cb = cols_of(a), cols_of(b)
    s += 2 * len(ca & cb)
    fa = {norm(x) for x in a['filters'] + a['scope']}
    fb = {norm(x) for x in b['filters'] + b['scope']}
    s += len(fa & fb)
    return s


def pair_queries(olds, news):
    """Greedy best-overlap pairing; unmatched entries are reported as such."""
    cand = []
    for i, o in enumerate(olds):
        for j, n in enumerate(news):
            sc = score(o[1], n[1])
            if sc > 0:
                cand.append((sc, i, j))
    cand.sort(reverse=True)
    uo, un, pairs = set(), set(), []
    for sc, i, j in cand:
        if i in uo or j in un:
            continue
        uo.add(i)
        un.add(j)
        pairs.append((i, j, sc))
    return pairs, [i for i in range(len(olds)) if i not in uo], \
                  [j for j in range(len(news)) if j not in un]


def loc(entry):
    return '%s:%d' % (entry[0]['file'], entry[0]['line'])


# This schema prefixes every column with its table code (USB_, OGI_, PRT_ …),
# which makes a reliable token for "does NEW touch this datum at all".
COLTOK = re.compile(r'\b[A-Za-z]{2,5}_[A-Za-z]\w*\b')


def toks(s):
    return {t.lower() for t in COLTOK.findall(s)}


def load_migrations(root):
    """legacy column -> new column, as documented in NEW javadoc.

    ms-consumer records its renames inline, e.g.
    `{@code OGP_LST_ListingID} -> {@code ORD_VLO_VendorLocationID}`. Treating a
    documented rename as a dropped rule would be wrong, so these are surfaced
    as MIGRATED with the mapping quoted for the reader to confirm.
    """
    import os
    mp = {}
    if not root:
        return mp
    pat = re.compile(r'\{@code\s+([A-Za-z]{2,5}_[A-Za-z]\w*)\s*\}\s*(?:→|⇒|->|=>)'
                     r'\s*\{@code\s+([A-Za-z]{2,5}_[A-Za-z]\w*)\s*\}')
    for dp, _, fs in os.walk(os.path.join(root, 'src/main/java')):
        for f in fs:
            if f.endswith('.java'):
                t = open(os.path.join(dp, f), encoding='utf-8', errors='replace').read()
                for a, b in pat.findall(t):
                    mp.setdefault(a.lower(), set()).add(b)
    return mp


MIGRATED = load_migrations(A.new_root)


def verdict(old_clause, new_norm_set, new_index, kind):
    """Satisfied / changed / absent, judged across the whole NEW path.

    A rewrite that moves a datum to a migrated table keeps the same column
    token but changes the clause; that is a change to review, not a dropped
    rule, and conflating the two overstates the gap.
    """
    if norm(old_clause) in new_norm_set:
        return None
    hit = [t for t in toks(old_clause) if t in new_index]
    if hit:
        near = new_index[hit[0]][0]
        return ('%s CHANGED in NEW — OLD: %s | NEW: %s'
                % (kind, old_clause, near))
    renamed = [(t, sorted(MIGRATED[t])[0]) for t in toks(old_clause)
               if t in MIGRATED and sorted(MIGRATED[t])[0].lower() in new_index]
    if renamed:
        return ('%s MIGRATED in NEW — OLD: %s | NEW renames %s'
                % (kind, old_clause,
                   ', '.join('%s to %s' % (a, b) for a, b in renamed)))
    return '%s ABSENT from NEW: %s' % (kind, old_clause)


def build_index(entries):
    """column token -> the NEW clauses that mention it."""
    idx = {}
    for _, d in entries:
        clauses = list(d['filters']) + list(d['scope']) + \
                  [c for t, c in d['joins'] if c] + list(d['reads'])
        for c in clauses:
            for t in toks(c):
                idx.setdefault(t, []).append(re.sub(r'\s+', ' ', c).strip())
    return idx


def path_sets(entries):
    """Union of every rule the side applies, across all its queries.

    A gap is only real if NO query on the NEW path applies the rule. Judging
    against the paired query alone reports a rule as missing merely because the
    rewrite moved it into a sibling query.
    """
    s = {'filters': set(), 'scope': set(), 'joins': set(), 'cols': set(),
         'order': set(), 'limit': set(), 'group': set()}
    for _, d in entries:
        s['filters'] |= {norm(x) for x in d['filters']}
        s['scope'] |= {norm(x) for x in d['scope']}
        s['joins'] |= {norm(c) for t, c in d['joins'] if c}
        s['cols'] |= cols_of(d)
        for k in ('order', 'limit', 'group'):
            if d[k]:
                s[k].add(norm(d[k]))
    return s


def diff_pair(o, n, N, IDX):
    """Old rules that the whole NEW path fails to reproduce."""
    gaps = []
    for x in o['filters']:
        v = verdict(x, N['filters'], IDX, 'Business filter')
        if v:
            gaps.append(v)
    for x in o['scope']:
        v = verdict(x, N['scope'], IDX, 'Scoping')
        if v:
            gaps.append(v)
    for t, c in o['joins']:
        if c:
            v = verdict(c, N['joins'], IDX, 'Join %s' % t)
            if v:
                gaps.append(v)
    if o['order'] and norm(o['order']) not in N['order']:
        gaps.append('Ordering not reproduced in NEW — OLD: %s' % o['order'])
    if o['limit'] and norm(o['limit']) not in N['limit']:
        gaps.append('Row limit not reproduced in NEW — OLD: %s' % o['limit'])
    if o['group'] and norm(o['group']) not in N['group']:
        gaps.append('Grouping not reproduced in NEW — OLD: %s' % o['group'])
    if not o['write']:
        absent = [c for c in o['reads']
                  if norm_col(c) not in N['cols'] and not (toks(c) & set(IDX))]
        if absent:
            gaps.append('Columns NEW never returns: %s%s'
                        % (', '.join(absent[:6]), ' …' if len(absent) > 6 else ''))
    return gaps


# ------------------------------------------------------------------ build ---
def side(tr):
    """[(meta, decomposed)] for one side, or None when nothing was opened."""
    if tr is None:
        return None
    return [(s, decompose(s['q'])) for s in tr['sql']]


def main():
    stats = {}
    for r in ROWS:
        nk = 'new|%s|%s' % (r['verb'], (r.get('new_path') or '').replace(A.new_ctx, '', 1))
        ok = 'old|%s|%s' % (r['verb'], (r.get('old_path') or '').replace(A.old_ctx, '', 1))
        ntr = TRACE.get(nk) if (r.get('new_path') or '') not in ('', '—') else None
        otr = TRACE.get(ok) if (r.get('old_path') or '') not in ('', '—') else None
        news, olds = side(ntr), side(otr)

        def render(entries, tr):
            if entries is None:
                return ''
            if not entries:
                if tr['entered'] and not tr['touched_repo']:
                    return ('N/A — no SQL on this path (opened %s)'
                            % ', '.join(tr['visited'][:3]))
                return 'UNKNOWN — repo/SQL not opened'
            out = []
            for i, (meta, d) in enumerate(entries, 1):
                out.append('[Q%d] %s:%d' % (i, meta['file'], meta['line']))
                out += ['   • ' + x for x in describe(d, meta['q'])]
            return '\n'.join(out)

        old_logic = render(olds, otr)
        new_logic = render(news, ntr)

        # ---- functional match + gaps ---------------------------------
        both = bool(olds) and bool(news)
        if r['status'] == 'Missing in new':
            match = 'No — endpoint absent from NEW'
            gaps = (['Entire OLD data path is unimplemented in NEW (%d quer%s).'
                     % (len(olds), 'y' if len(olds) == 1 else 'ies')]
                    + ['Q%d %s: %s' % (i + 1, loc(olds[i]), '; '.join(
                        describe(olds[i][1], olds[i][0]['q'])[:3]))
                       for i in range(min(len(olds), 4))]) if olds else \
                   ['Endpoint absent from NEW; OLD handler reaches no SQL either.']
        elif r['status'] == 'New only':
            match = 'N/A — new endpoint, no OLD counterpart'
            gaps = ['Nothing missing: this endpoint does not exist in OLD.']
        elif olds is None or news is None:
            match = 'UNKNOWN — one side not opened'
            gaps = ['UNKNOWN — did not open both sides.']
        elif not olds and not news:
            match = ('N/A — neither side reaches SQL'
                     if (otr['entered'] and ntr['entered']
                         and not otr['touched_repo'] and not ntr['touched_repo'])
                     else 'UNKNOWN — repo/SQL not opened')
            gaps = ['N/A — no SQL on either side.'] if match.startswith('N/A') \
                else ['UNKNOWN — repo/SQL not opened.']
        elif olds and not news:
            match = 'No — NEW reaches no SQL'
            gaps = ['NEW handler issues no query; OLD issues %d.' % len(olds)] + \
                   ['Q%d %s not reproduced in NEW.' % (i + 1, loc(olds[i]))
                    for i in range(min(len(olds), 5))]
        elif news and not olds:
            match = 'No — OLD reached no SQL'
            gaps = ['Nothing missing from NEW; OLD issued no query on this path.']
        else:
            pairs, un_old, un_new = pair_queries(olds, news)
            NSET, NIDX = path_sets(news), build_index(news)
            gaps, ok_pairs = [], 0
            for i, j, sc in pairs:
                d = diff_pair(olds[i][1], news[j][1], NSET, NIDX)
                if d:
                    gaps.append('OLD Q%d (%s) vs NEW Q%d (%s):'
                                % (i + 1, loc(olds[i]), j + 1, loc(news[j])))
                    gaps += ['   – ' + x for x in d]
                else:
                    ok_pairs += 1
            for i in un_old:
                d = diff_pair(olds[i][1], None, NSET, NIDX)
                if not d:
                    ok_pairs += 1
                    continue
                gaps.append('OLD Q%d (%s) has no matching NEW query; unmet rules:'
                            % (i + 1, loc(olds[i])))
                gaps += ['   – ' + x for x in d]
            if not gaps:
                match = 'Match — every OLD rule reproduced in NEW (%d quer%s)' \
                        % (ok_pairs, 'y' if ok_pairs == 1 else 'ies')
                gaps = ['None — all OLD filters, joins, scoping and ordering '
                        'are present in NEW.']
            elif ok_pairs or pairs:
                match = 'Partial — %d/%d OLD queries fully reproduced' \
                        % (ok_pairs, len(olds))
            else:
                match = 'No — no OLD query has a matching NEW query'

        # ---- table presence, both directions --------------------------
        otabs = otr['tables'] if otr else []
        ntabs = ntr['tables'] if ntr else []
        old_bare = {t.split('.')[-1].lower() for t in otabs}
        miss_newdev = sorted(t for t in otabs if t.split('.')[-1].lower() not in NEW_ALL_BARE)
        new_vs_old = sorted(t for t in ntabs if t.split('.')[-1].lower() not in old_bare)

        if not otabs:
            c_missing = 'N/A — OLD reaches no table on this path'
        elif miss_newdev:
            c_missing = ('%d OLD table(s) not referenced anywhere in NEW code:\n'
                         % len(miss_newdev)) + '\n'.join('• ' + t for t in miss_newdev) + \
                        '\n(code-level; newdev DB not queried)'
        else:
            c_missing = 'None — every OLD table is referenced somewhere in NEW code'

        if not ntabs:
            c_new = 'N/A — NEW reaches no table on this path'
        elif new_vs_old:
            c_new = ('%d table(s) NEW uses that this OLD path does not:\n' % len(new_vs_old)) + \
                    '\n'.join('• ' + t for t in new_vs_old)
        else:
            c_new = 'None — NEW uses no table beyond the OLD path'

        # ---- use case (unchanged source rules) -------------------------
        what = (r.get('what') or '').strip()
        prd = (r.get('prd_expected') or '').strip()
        caller = ('An authenticated app user' if str(r.get('auth', '')).startswith('JWT')
                  else 'An unauthenticated client')
        if what and not what.startswith('UNKNOWN'):
            use_case = '%s calls %s to: %s' % (caller, r['verb'], what.rstrip('.') + '.')
        elif prd and not prd.startswith('UNKNOWN'):
            use_case = '%s calls %s. PRD: %s' % (caller, r['verb'], prd)
        else:
            use_case = 'UNKNOWN — no use case in handler javadoc or PRD'

        r.update(use_case=use_case, old_logic=old_logic, new_logic=new_logic,
                 logic_match=match, logic_missing='\n'.join(gaps),
                 tables_missing_newdev=c_missing, tables_new_vs_old=c_new,
                 db_verified=NOT_VERIFIED)
        for k in ('old_sql', 'new_sql', 'newdev_status', 'db_same', 'logic',
                  'missing_logic', 'func_match'):
            r.pop(k, None)
        r['sql_gap'] = not (match.startswith('Match') or match.startswith('N/A'))
        head = match.split(' —')[0].split(' -')[0]
        # Short, low-cardinality value so the column filter stays usable.
        r['logic_match_cat'] = head
        stats[head] = stats.get(head, 0) + 1

    json.dump(ROWS, open(A.rows, 'w'), indent=1)
    print('rows: %d   SQL/logic gap rows: %d'
          % (len(ROWS), sum(1 for r in ROWS if r['sql_gap'])))
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print('  %-38s %d' % (k, v))


if __name__ == '__main__':
    main()
