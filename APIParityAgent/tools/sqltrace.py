#!/usr/bin/env python3
"""STEP SQL-FUNC stage 1 — trace controller -> service -> repository/DAO -> SQL.

Emits, per (side, verb, path): the tables the handler actually reaches and the
SQL/JPQL it issues, each with file:line. Anything not reached by an opened file
stays empty so the caller can render UNKNOWN rather than guess.

Usage:
    python3 sqltrace.py --new-root DIR --old-root DIR \
                        [--new-inv new.json] [--old-inv old.json] \
                        [--out sqltrace.json]

The inventory files are the STEP 1 / STEP 2 outputs; each row needs `cls`,
`method`, `verb` and `path` (path WITHOUT the context-path prefix).
"""
import argparse
import json
import os
import re
import sys

CLASS_DECL = re.compile(
    r'\b(?:public\s+|abstract\s+|final\s+)*(class|interface)\s+(\w+)')
# svc-consumer declares many @Autowired collaborators package-private, so the
# modifier cannot be required. Locals are matched too, which is harmless here.
FIELD = re.compile(
    r'(?:(?:private|protected|public|static|final)\s+)*([A-Z]\w*)(?:<[^>]*>)?\s+(\w+)\s*[;=]')
TABLE_ANN = re.compile(r'@Table\s*\(([^)]*)\)')
ENTITY_OF_REPO = re.compile(
    r'extends\s+(?:Jpa|Crud|PagingAndSorting|JpaSpecificationExecutor)\w*Repository\s*<\s*([A-Za-z_]\w*)')


KEYWORDS = {'if', 'for', 'while', 'switch', 'catch', 'return', 'new', 'synchronized',
            'try', 'do', 'else', 'throw', 'super', 'this', 'assert', 'instanceof'}
REAL_TABLE = re.compile(r'^(?:[A-Za-z_]\w*\.)?(?:tbl_|TBL_)\w+$')
ENTITY_NAME = re.compile(r'^[A-Z][a-z]\w*$')


def keep_table(t):
    """Reject fragments produced by `"FROM " + SCHEMA + ".tbl_x"` concatenation.

    Only a fully-formed table name or a JPQL entity name is trustworthy; the
    raw SQL is still displayed, so nothing verifiable is lost by dropping these.
    """
    if REAL_TABLE.match(t):
        return True
    return bool(ENTITY_NAME.match(t)) and not t.isupper()


def load(root):
    files = {}
    for dp, _, fs in os.walk(os.path.join(root, 'src/main/java')):
        for f in sorted(fs):
            if f.endswith('.java'):
                p = os.path.join(dp, f)
                files[f[:-5]] = (os.path.relpath(p, root),
                                 open(p, encoding='utf-8', errors='replace').read())
    return files


def line_of(text, idx):
    return text.count('\n', 0, idx) + 1


def block_after(text, idx):
    """Body of the brace block starting at/after idx."""
    b = text.find('{', idx)
    if b < 0:
        return ''
    depth, j, instr, ch = 0, b, False, None
    while j < len(text):
        c = text[j]
        if instr:
            if c == '\\':
                j += 2
                continue
            if c == ch:
                instr = False
        elif c in '"\'':
            instr, ch = True, c
        elif text.startswith('//', j):
            k = text.find('\n', j)
            j = len(text) if k < 0 else k
            continue
        elif text.startswith('/*', j):
            k = text.find('*/', j)
            j = len(text) if k < 0 else k + 2
            continue
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[b + 1:j]
        j += 1
    return text[b + 1:]


def match_paren(text, open_idx):
    depth, j, instr, ch = 0, open_idx, False, None
    while j < len(text):
        c = text[j]
        if instr:
            if c == '\\':
                j += 2
                continue
            if c == ch:
                instr = False
        elif c in '"\'':
            instr, ch = True, c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def method_bodies(text, name):
    """Every declaration of `name` (not call sites) in this file.

    Overloads matter: a handler often delegates to a wider overload that holds
    all the data access, so reading only the first declaration loses the SQL.
    """
    out = []
    for m in re.finditer(r'(?<![\w.])' + re.escape(name) + r'\s*\(', text):
        close = match_paren(text, text.index('(', m.start()))
        if close < 0:
            continue
        # A declaration is followed by a body; a call is followed by ';' or an
        # operator. `throws` may sit in between.
        if not re.match(r'\s*(?:throws\s+[\w., <>]+)?\s*\{', text[close + 1:]):
            continue
        out.append((block_after(text, close), line_of(text, m.start())))
    return out


class Index:
    def __init__(self, root, label):
        self.root, self.label = root, label
        self.files = load(root)
        self.tables = {}      # class -> table name
        self.repo_entity = {}  # repo class -> entity class
        for cls, (rel, txt) in self.files.items():
            t = TABLE_ANN.search(txt)
            if t:
                nm = re.search(r'name\s*=\s*"([^"]+)"', t.group(1)) or \
                     re.match(r'\s*"([^"]+)"', t.group(1))
                if nm:
                    self.tables[cls] = nm.group(1)
            r = ENTITY_OF_REPO.search(txt)
            if r:
                self.repo_entity[cls] = r.group(1)

    def fields(self, cls):
        rel, txt = self.files[cls]
        return {n: t for t, n in FIELD.findall(txt)}

    def impl_of(self, typ):
        for cand in (typ + 'Impl', typ):
            if cand in self.files:
                yield cand

    def sql_in(self, cls, method):
        """SQL/JPQL + tables reachable from cls.method (repo layer)."""
        out = {'sql': [], 'tables': set()}
        if cls not in self.files:
            return out
        rel, txt = self.files[cls]
        # Find the declaration of `method`, then read the annotation block that
        # immediately precedes it. A @Query elsewhere in the file is not ours.
        for m in re.finditer(r'\b' + re.escape(method) + r'\s*\(', txt):
            head = txt.rfind(';', 0, m.start())
            head = max(head, txt.rfind('}', 0, m.start()))
            ann = txt[head + 1:m.start()]
            if '@Query' not in ann:
                continue
            qa = ann[ann.index('@Query'):]
            # ms-consumer writes most queries as Java text blocks.
            tb = re.search(r'"""(.*?)"""', qa, re.S)
            if tb:
                joined = tb.group(1)
            else:
                q = re.search(
                    r'(?:value\s*=\s*)?"((?:[^"\\]|\\.)*(?:"\s*\+\s*"(?:[^"\\]|\\.)*)*)"', qa)
                if not q:
                    continue
                joined = re.sub(r'"\s*\+\s*"', '', q.group(1))
            joined = re.sub(r'\s+', ' ', joined).strip()
            if joined:
                # Full text, not a preview: a clipped WHERE clause would look
                # like a predicate the other side is missing.
                out['sql'].append((rel, line_of(txt, head + 1), joined[:4000]))
        ent = self.repo_entity.get(cls)
        if ent and ent in self.tables:
            out['tables'].add(self.tables[ent])
        for _, ln, q in out['sql']:
            for t in re.findall(r'(?:from|join|into|update)\s+([A-Za-z_][\w.]*)', q, re.I):
                # JPQL names the entity; map it to its @Table when we opened one.
                t = self.tables.get(t, t)
                if keep_table(t):
                    out['tables'].add(t)
        return out

    def trace(self, controller, handler, maxdepth=3):
        """Walk controller.handler -> services -> repositories collecting SQL."""
        res = {'sql': [], 'tables': set(), 'visited': [], 'services': set(),
               'touched_repo': False}
        if controller not in self.files:
            return res
        seen = set()

        def walk(cls, meth, depth):
            if depth > maxdepth or (cls, meth) in seen or cls not in self.files:
                return
            seen.add((cls, meth))
            rel, txt = self.files[cls]
            bodies = method_bodies(txt, meth)
            if not bodies:
                return
            body = '\n'.join(b for b, _ in bodies)
            res['visited'].append('%s#%s' % (cls, meth))
            flds = self.fields(cls)
            # Data access usually sits in private helpers of the same class, so
            # follow bare (receiver-less) calls before leaving the class.
            # Sorted, not set order: PYTHONHASHSEED would otherwise vary the
            # visit order and change which file:line a cell cites between runs.
            for local in sorted(set(re.findall(r'(?<![\w.])(\w+)\s*\(', body))):
                if local not in KEYWORDS and local != meth and method_bodies(txt, local):
                    walk(cls, local, depth)
            for fname, mname in re.findall(r'\b(\w+)\s*\.\s*(\w+)\s*\(', body):
                typ = flds.get(fname)
                if not typ:
                    continue
                if re.search(r'Repository|Dao|DAO', typ):
                    res['touched_repo'] = True
                    got = self.sql_in(typ, mname)
                    res['sql'] += got['sql']
                    res['tables'] |= got['tables']
                    if typ in self.repo_entity and self.repo_entity[typ] in self.tables:
                        res['tables'].add(self.tables[self.repo_entity[typ]])
                    # DAOs hold no @Query of their own; they delegate to repos.
                    if re.search(r'Dao|DAO', typ):
                        for impl in self.impl_of(typ):
                            walk(impl, mname, depth + 1)
                elif re.search(r'Service|Manager|Helper|Support|Client|Facade', typ):
                    res['services'].add(typ)
                    for impl in self.impl_of(typ):
                        walk(impl, mname, depth + 1)
            # native SQL / fragments referenced by constant classes
            for frag in re.findall(r'\b([A-Z]\w*(?:SqlFragments|Sql|Queries))\b', body):
                if frag in self.files:
                    frel, ftxt = self.files[frag]
                    for q in re.findall(r'"((?:[^"\\]|\\.)*(?:FROM|from)[^"]*)"', ftxt)[:6]:
                        res['sql'].append((frel, 0, re.sub(r'\s+', ' ', q)[:600]))
                        for t in re.findall(r'(?:from|join)\s+([A-Za-z_][\w.]*)', q, re.I):
                            res['tables'].add(t)

        walk(controller, handler, 0)
        seen_q, uniq = set(), []
        for f, l, q in res['sql']:
            if (f, l) not in seen_q:
                seen_q.add((f, l))
                uniq.append((f, l, q))
        res['sql'] = uniq
        return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--new-root', required=True, help='NEW module root (contains src/main/java)')
    ap.add_argument('--old-root', required=True, help='OLD repo root (contains src/main/java)')
    ap.add_argument('--new-inv', default='new.json')
    ap.add_argument('--old-inv', default='old.json')
    ap.add_argument('--out', default='sqltrace.json')
    a = ap.parse_args()

    out = {}
    for label, root, inv in (('new', a.new_root, a.new_inv),
                             ('old', a.old_root, a.old_inv)):
        idx = Index(root, label)
        rows = json.load(open(inv))
        for r in rows:
            t = idx.trace(r['cls'], r['method'])
            out['%s|%s|%s' % (label, r['verb'], r['path'])] = {
                'tables': sorted(t['tables']),
                # Keep every query: the functional diff compares predicate sets,
                # so a truncated list would invent "missing in new" rules.
                'sql': [{'file': f, 'line': l, 'q': q} for f, l, q in t['sql']],
                'visited': t['visited'][:8],
                'services': sorted(t['services'])[:6],
                'touched_repo': t['touched_repo'],
                'entered': bool(t['visited']),
            }
        if label == 'new':
            # Module-wide table index: "absent from NEW code" must be judged
            # against the whole module, not just this handler's call path.
            allt = set()
            for cls, (rel, txt) in idx.files.items():
                for q in re.findall(r'"((?:[^"\\]|\\.)*)"', txt):
                    for tk in re.findall(r'(?:from|join|into|update)\s+([A-Za-z_][\w.]*)',
                                         q, re.I):
                        tk = idx.tables.get(tk, tk)
                        if keep_table(tk):
                            allt.add(tk)
            allt |= set(idx.tables.values())
            out['__new_all_tables__'] = sorted(allt)
        n = sum(1 for k, v in out.items()
                if k.startswith(label) and isinstance(v, dict) and (v['tables'] or v['sql']))
        tot = sum(1 for k in out if k.startswith(label))
        print('%s: %d/%d handlers resolved to tables or SQL' % (label, n, tot))
    json.dump(out, open(a.out, 'w'), indent=1)
    print('wrote', a.out)


if __name__ == '__main__':
    main()
