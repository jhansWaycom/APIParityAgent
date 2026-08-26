# APIParityCheck — the `APIParityAgent` Cursor skill

`APIParityAgent` is a **read-only** Cursor Agent Skill that compares the HTTP API
surface of an **OLD** Way service against its **NEW** `way-services` module and
produces one self-contained HTML curl-comparison report plus a short chat summary.

It reads the source files that are already on disk in your working trees. It never
checks out a branch, never writes into `way-services` or any `svc-*` clone, and never
commits anything.

---

## What it produces

A single timestamped HTML file written **outside every git repo**, in your Documents
folder:

```
~/Documents/<MODULE>-old-new-curl-comparison-YYYYMMDD-HHmmss.html
```

The sheet has one de-duplicated row per `VERB + path` and these columns (defined in
[`APIParityAgent/reference.md`](APIParityAgent/reference.md)):

| Group | Columns |
|---|---|
| Identity | `#`, `Method`, `What this API does`, `Old source`, `Old request path`, `New request path` |
| Reproduction | `Old curl`, `New curl` |
| Parity | `Status` (In both / In both (moved) / Missing in new / New only) |
| Access | `Auth`, `Data input`, `Validation`, `Required inputs` |
| Spec | `Expected behaviour (PRD)`, `PRD match` |
| Data layer | `Old DB logic`, `New DB logic`, `Logic match?`, `Missing / changed in new`, `Tables missing in newdev`, `Tables new vs old`, `DB data verified?` |
| Linkage | `Co-dependent APIs`, `Controllers / GitHub`, `Use case` |

Filter tabs: All, In both, Missing in new, New only, Data input not needed, Data input
needed, Chains, PRD gap, SQL/logic gap.

Every run ends with a **self-assessment scorecard** in chat, grading its own evidence.

---

## The honesty contract

This is the part that makes the report worth trusting, so do not weaken it when you
edit the skill:

- Every cell comes from a file the agent actually opened, or it says `UNKNOWN — <why>`.
- `Required inputs` come only from the opened method signature. Spring `@RequestParam`
  is `required=true` unless `required=false` or a `defaultValue` is present.
- Full path = context-path + class `@RequestMapping` + method mapping, with
  `UrlConstants` / `static String` constants resolved.
- Expected behaviour is quoted only from a Confluence page under the **Service Rewrites**
  folder (id `43057153`). No PRD page, no PRD text — the cell says `UNKNOWN`.
- Table names come only from opened `@Table` / `@Query`. Never guessed.
- `Logic match?` must be `UNKNOWN` whenever either side was not traced.

---

## Prerequisites

| Requirement | Why | Check |
|---|---|---|
| Cursor with Agent Skills enabled | runs the skill | Cursor Settings → Skills |
| `python3` (3.8+) | the four SQL-trace tools | `python3 --version` |
| `git` | reading the working trees | `git --version` |
| GitHub CLI `gh`, authenticated | confirming/cloning the OLD repo under `Way-com` | `gh auth status` |
| Access to the `Way-com` GitHub org | OLD + NEW sources are private | `gh repo view Way-com/way-services` |
| Atlassian MCP connected (`wayglobal.atlassian.net`) | reading Service Rewrites PRDs | Cursor Settings → MCP |

Without Atlassian MCP the agent still runs — the PRD columns will correctly read
`UNKNOWN` instead of being invented.

### Local checkouts you need

The agent compares two working trees that must already exist on your machine:

- **NEW** — your `way-services` clone, specifically the module directory
  (for example `way-services/ms-consumer`).
- **OLD** — a sibling clone of the legacy service (for example `svc-consumer`),
  checked out next to `way-services`, not inside it.

---

## Install

### Option A — install script

```bash
git clone https://github.com/jhansWaycom/APIParityCheck.git
cd APIParityCheck
./install.sh
```

`install.sh` copies `APIParityAgent/` into `~/.cursor/skills/`, backing up any existing
copy to `~/.cursor/skills/APIParityAgent.bak-<timestamp>` first.

### Option B — manual copy

```bash
git clone https://github.com/jhansWaycom/APIParityCheck.git
mkdir -p ~/.cursor/skills
cp -R APIParityCheck/APIParityAgent ~/.cursor/skills/
```

### Verify the install

```bash
ls ~/.cursor/skills/APIParityAgent
# expected: SKILL.md  reference.md  tools
head -3 ~/.cursor/skills/APIParityAgent/SKILL.md
# expected: ---  /  name: api-parity-agent
```

Then **fully restart Cursor** (Cmd+Q, not just window reload) so the skill is picked up.

---

## Run it

Open a Cursor chat in the workspace that contains your `way-services` clone and type
one of the trigger phrases:

```
APIParityAgent compare ms-consumer
```

Other phrases that trigger it: `compare ms-orders`, `ms-search APIs`, `old vs new API`,
`API parity`, `curl catalog`, `live parity run`, `curl comparison HTML`. The module name
is extracted from the command.

The agent will ask for anything it cannot derive — most often the OLD repo name and the
old/new context-path prefixes.

### Reading the report

```bash
mkdir -p /tmp/apiserve
cp ~/Documents/ms-consumer-old-new-curl-comparison-*.html /tmp/apiserve/report.html
cd /tmp/apiserve && python3 -m http.server 8899
# open http://127.0.0.1:8899/report.html
```

---

## The SQL/logic tools

`APIParityAgent/tools/` holds the four scripts the agent shells out to for the data-layer
columns. They are plain stdlib Python and can be run by hand:

| Script | Stage | Purpose |
|---|---|---|
| `sqltrace.py` | 1 | Traces controller → service → repository/DAO → SQL, emitting per `(side, verb, path)` the tables reached and the SQL/JPQL issued, each with `file:line`. Anything not reached by an opened file stays empty. |
| `sqlfunc.py` | 2 | Decomposes each query into the rules it applies (reads, joins, filters with literals, caller scoping, ordering, limits, aggregation), pairs each OLD query with its nearest NEW counterpart, and reports which rules NEW does not implement. |
| `sqlcols.py` | 2 | Appends the eight use-case / SQL / logic columns to `rows.json` from the trace. Cells the trace never reached become `UNKNOWN` rather than a guessed table. |
| `gate_sql.py` | 3 | Independent gate over the rendered HTML. Fails the run if the sheet quotes a SQL clause absent from the repo, cites an unresolvable `file:line`, claims a DB result never run, or drops a mandated column. |

Typical sequence:

```bash
cd ~/.cursor/skills/APIParityAgent

python3 tools/sqltrace.py \
  --new-root <NEW module dir> \
  --old-root <OLD repo dir> \
  --new-inv new.json --old-inv old.json --out sqltrace.json

python3 tools/sqlfunc.py --new-ctx /ms-consumer --old-ctx /way-consumer \
  --rows rows.json --trace sqltrace.json

python3 tools/sqlcols.py --new-ctx /ms-consumer --old-ctx /way-consumer \
  --rows rows.json --trace sqltrace.json

python3 tools/gate_sql.py \
  --new-root <NEW module dir> --old-root <OLD repo dir> \
  --html-glob '~/Documents/*-old-new-curl-comparison-*.html'
```

`new.json` / `old.json` are the STEP 1 / STEP 2 controller inventories the agent builds;
each row needs `cls`, `method`, `verb`, and `path` (path **without** the context-path).

---

## Repo layout

```
APIParityCheck/
├── README.md
├── install.sh
├── .gitignore
└── APIParityAgent/          <- copy this whole directory into ~/.cursor/skills/
    ├── SKILL.md             <- agent instructions + YAML frontmatter
    ├── reference.md         <- HTML report spec (columns, tabs, dedup rules)
    └── tools/
        ├── sqltrace.py
        ├── sqlfunc.py
        ├── sqlcols.py
        └── gate_sql.py
```

---

## Safety notes

- The agent is **read-only** on source: no `checkout`, no branch pinning, no writes into
  `way-services` or a `svc-*` clone, no `git add` of the report.
- Reports land in `~/Documents/`, deliberately outside every git repo, and are never
  overwritten (the filename is timestamped).
- Curl examples use `${TOKEN:-}` / `${COOKIE:-}` / `${ES_URL:-}` placeholders. **Never
  paste a real bearer token, cookie, or password into a report or a commit.** Export
  them in your shell for the length of the run only.
- Generated reports can contain internal endpoint and schema detail. Treat them as
  internal, and redact PII before sharing outside the team.

---

## Contributing

The skill is prose plus four Python scripts, so changes are ordinary edits:

1. Branch off `main`.
2. Edit `APIParityAgent/SKILL.md` (behaviour), `reference.md` (report spec), or `tools/`.
3. If you change the YAML frontmatter `description`, keep the trigger phrases — that is
   what makes Cursor load the skill.
4. Re-install with `./install.sh`, restart Cursor, and do a real run against a module.
5. Open a PR describing what changed in the report output.

Please keep the honesty contract intact. A cell that guesses is worse than a cell that
says `UNKNOWN`.
