# HTML curl-comparison report (APIParityAgent)

Write exactly one self-contained `.html` file **outside every git repo**,
in the user's Documents folder, with a **local timestamp in the filename**.

Path template:

`/Users/<user>/Documents/<MODULE>-old-new-curl-comparison-YYYYMMDD-HHmmss.html`

Example:

`/Users/jhansibendi/Documents/ms-consumer-old-new-curl-comparison-20260824-124400.html`

Stamp from `date +%Y%m%d-%H%M%S` at write time. Never overwrite a previous
report. Never write
`<MODULE>-old-new-curl-comparison.html` without a timestamp.

Never write it under `way-services/`, `~/Documents/newrepo/`, or a `svc-*` clone. Never `git add` it.

## Columns (order is mandatory)

| Column | Rule |
|--------|------|
| # | 1-based after filters |
| Method | GET / POST / PUT / PATCH / DELETE |
| What this API does | From `@Operation` / `@ApiOperation` / javadoc **on this mapping only**. Never invent. Never copy the previous method. Prefer NEW, else OLD. If none: `UNKNOWN — no @Operation/javadoc on this handler`. |
| Expected behaviour (PRD) | Quote from an opened page under Confluence folder `43057153` (Service Rewrites) plus that page URL. If none: `UNKNOWN — not stated in Service Rewrites PRDs (folder 43057153)`. Never copy `@Operation` into this cell. Never invent. |
| PRD match | `Match` / `Partial` / `Gap` / `UNKNOWN`. UNKNOWN whenever Expected behaviour is UNKNOWN. Match only if the quoted PRD is what the opened handler does (file:line). |
| Old source | `svc-consumer`, `svc-rmconsumer`, … |
| Old request path | Full `{old-context}{path}` or blank. Never truncate with `...` / ellipsis. Wrap the cell; `white-space: pre-wrap`; no `text-overflow: ellipsis`. |
| New request path | Full `{new-context}{path}` or blank. Same: never `...`. |
| Old curl | Full curl or blank if new-only |
| New curl | Full curl or blank if missing in new |
| Status | `In both` / `In both (moved)` (path after context-path differs) / `Missing in new` / `New only`. Render as a badge: green / blue / red / amber. |
| Auth | `Public` / `Public + Entitlement` / `JWT` / `JWT + Entitlement`. From the opened `SecurityFilterChain` + real (non-javadoc) `@PreAuthorize`. Independent of Data input. See STEP AUTH in SKILL.md. |
| Data input | `Needed` / `Not needed` |
| Validation | `Manual — user supplies fixtures` if Needed; `Agent can run` if Not needed |
| Required inputs | Path vars, required query (name + type), optional query, DTO / multipart. `None` only if the method signature was opened and has no required bindings. Else `UNKNOWN — method signature not opened`. |
| Co-dependent APIs | Chain ID + related `VERB path` list, or `None` |
| Controllers / GitHub | Blob URLs with `#L<line>` |
| Use case | From opened `@Operation` / PRD quote already in those columns. Else `UNKNOWN — no use case in handler javadoc or PRD`. Never invent from the method name. |
| Old DB logic (functional) | The rules the OLD queries apply (what they return, join conditions, business filters with literals, caller/resource scoping, grouping, ordering, limits) + file:line. Blank when New only. `UNKNOWN — <why>` when that side was not traced; say which side and how far the trace got. Render in a scrollable `.sqlbox`. |
| New DB logic (functional) | Same for NEW. Blank if Missing in new. |
| Logic match? | Badge `Match` / `Partial` / `No` / `UNKNOWN` / `N/A`, plus a one-line reason under it. **`UNKNOWN` is mandatory when either side is untraced** — with one side blank you cannot claim Match and cannot claim a rule was lost. `N/A` for Missing in new / New only. |
| Missing / changed in new | Numbered OLD rules the whole NEW path fails to apply, each classified `CHANGED` (NEW touches the column differently — quote NEW text) / `MIGRATED` (documented rename, cite the NEW javadoc) / `ABSENT` (no NEW query references it). `None — both sides traced, no OLD rule lost` when clean. `UNKNOWN — <why>` when a side is untraced. |
| Tables missing in newdev | Code-level verdict (table referenced nowhere in the new module) or a quoted `SHOW TABLES` / SELECT error if a DB was queried. Never guess. `UNKNOWN — no DB queried and OLD tables not traced` is the honest value for a code-only run. |
| Tables new vs old | Tables each side references, labelled with where they came from (`NEW references (from opened repository code): …`, `OLD side: UNKNOWN — not traced`). |
| DB data verified? | `Yes` / `No` (you ran SELECT on both sides) / `Not verified — no DB access this run` / `Blocked — table missing in newdev` / `N/A — no SQL`. Render in `.warn` amber so nobody reads it as a pass. |

## Tabs (mandatory)

- All
- In both
- Missing in new (new curl blank)
- New only (old curl blank)
- Data input not needed
- Data input needed (manual validate)
- Chains (one card per Chain ID; hide `None`)
- PRD gap (PRD match is Gap or UNKNOWN)
- SQL/logic gap (`Logic match?` is No/Partial, or Missing / changed in new is a numbered list). When one side was never traced there are no gaps to show yet — rename this tab `SQL/logic unverified` and select the rows whose `Logic match?` is UNKNOWN.

Render tabs as pills (`.tab` / `.tab.on`), not plain buttons, and keep a
live `N of M rows` count in the toolbar.

## Dedup before render

Key: `VERB + lowercase path after context-path`, trailing slash stripped.

One row per key. `/foo` and `/foo/` merge. Commented mappings skipped.
Moved paths = one row with both Old and New paths filled.

## Data input

**Not needed:** GET/HEAD/OPTIONS, **and** you opened this method’s
signature, **and** no body, no path variable, no required query/header
except optional page/size/sort. JWT is Auth, not data input.

**Needed:** everything else, including “GET with no `{id}` in the path”
when `@RequestParam` is required (Spring default **required=true**).
Person using the agent fills `{ids}` and bodies. Agent must not invent
fixtures or auto-run those rows.

Curls for required query: `?serviceId={serviceId}` on the URL. Never
ship a bare `/v1/benefits/details` GET if the method requires `serviceId`.

## STEP PATH — class mapping + constants (check twice)

Full path after servlet context:

`join(class @RequestMapping, method mapping)`

Rules:

1. Quoted string: use it (`@RequestMapping("/v1/user")`).
2. Constant: open the defining class. Example from
   `svc-consumer` `legacy/constants/UrlConstants.java`:
   `SECURITY_USER_PROFILEMANAGEMENT = "/security/userProfileManagement"`.
   Class `@RequestMapping(UrlConstants.SECURITY_USER_PROFILEMANAGEMENT)`
   + method `@GetMapping("/user")` =
   `/security/userProfileManagement/user`.
   With context: `/way-consumer/security/userProfileManagement/user`.
3. Concatenated constants (`A + "/{userId}"` or `A + B`): resolve each
   piece, then concatenate. Unresolved piece → `UNKNOWN — unresolved
   constant <Name>` — never emit an empty method path `/`.
4. Pass 2: rebuild every HTML path from the opened files. If it does
   not match Pass 1, Pass 2 wins.

Worked miss (do not repeat): sheet had old
`/way-consumer/deleteProfilePic` and `/way-consumer/user`. Actual:
`/way-consumer/security/userProfileManagement/deleteProfilePic` and
`/way-consumer/security/userProfileManagement/user`. New get-profile
already uses `/ms-consumer/security/userProfileManagement/user` and
must pair as **In both**, not New only.

Same class of bug: `FeedbackLegacyController`
`@RequestMapping(UrlConstants.SECURITY)` → prefix `/security`.
`ImageController` method mappings that use `UrlConstants.IMAGE_*`
must be resolved before publish.

## STEP BINDING — extract from THIS method only

Do not classify from HTTP verb or path shape. Open the handler.

Spring defaults (do not “remember” otherwise):

| Annotation | Required? |
|------------|-----------|
| `@RequestParam("x")` / `@RequestParam String x` | **true** unless `required=false` or `defaultValue` is set |
| `@PathVariable` | true unless `required=false` |
| `@RequestHeader` | true unless `required=false` or `defaultValue` (skip Authorization / User-Agent / User-Agent-App — those are Auth, not data input) |
| `@RequestBody` / `@RequestPart` / `MultipartFile` | data input needed |

`page` / `size` / `sort` may stay optional for “Not needed” only if they
are optional or have `defaultValue`. A required `page` is Needed.

Parser rules (anti-hang, anti-bleed):

- Do not use catastrophic `re.S` class-matching across the whole file.
- Parameter list = the `(` … `)` of **this** Java method only.
- `@Operation` / javadoc window = text **after the previous class member
  ends** (`}` / `;` / class-body `{`) and **before this mapping**. Never
  copy the previous method’s summary (that bug labeled
  `/v1/benefits/details` as “Public benefit info”).
- The window may never start before the class body opens, so the javadoc
  above `@RestController` / `public class X` is out of scope. That leak
  put the controller javadoc on `DELETE /v1/user/document/delete/{documentId}`
  and on `DELETE /v1/profile-milestone/task`; both are really
  `UNKNOWN — no @Operation/javadoc on this handler`.
- `@Tag`, `@RequestMapping` comments, and response constants such as
  `FETCHED = "Documents fetched successfully."` are not descriptions.

If the method was not opened: Data input = Needed, Required inputs =
`UNKNOWN — method signature not opened`.

## STEP GATE (must pass before HTML publish)

For each row marked **Not needed**: re-open the method; if any required
binding exists, flip to Needed and put `{name}` on the curl.

For each required query: URL contains `?name={name}` (or `&name={name}`).

For each row: Pass 2 path = join(resolved class mapping, resolved method
mapping). Must match Old/New request path and the URL inside the curl.

Description verb sweep: DELETE rows must not read “get/fetch/retrieve/
list/return”; POST/PUT/PATCH rows must not read “get/fetch/list”; GET
rows must not read “delete/create/update”. On a hit, re-open the
handler. Keep verbatim text that really is in the method window (note
`verb-mismatch confirmed in code`); otherwise `UNKNOWN`. Rewording the
sentence to match the verb is fabrication and fails the gate.

Chains sweep: each step has a complete curl plus either
`Inputs needed: …` (identical to that row’s Required inputs) or exactly
`No input needed — runnable as-is`. No placeholders on no-input steps.

## STEP USER EVIDENCE

User curl + JSON body is evidence. Match verb/path to the controller
file:line. If they got 400 Missing Request Parameter `serviceId`, the
row is Needed and the curl must include `?serviceId={serviceId}`.
Do not invent a 200 payload or a fixture id. Redact JWTs.

Worked correction: newdev `GET /ms-consumer/v1/benefits/details` without
query → 400 `Required parameter 'serviceId' is missing` matches
`BenefitsController.getBenefitDetails` `@RequestParam("serviceId")`.

## Co-dependent chains (examples — still confirm in code)

- `LICENSE-PLATE`: POST/GET/PUT/DELETE `/v1/user/license-plate`
- `CHECK-IN`: GET public list + POST user checkin
- `REVIEW`: POST public review + GET listing / listingaverage / auth GET
- `WALLET-PIN`: summary/tx vs pin/otp/verify (if present)
- `DOCUMENT`: upload → get → delete → share
- `WAVE-OAUTH`: connect → callback → connect-token → disconnect
- `RM-APPT`: reschedule / status / events / resend

Isolated APIs: Co-dependent APIs = `None`.

Chains tab renders a runbook per Chain ID, in `create → read → update →
delete` order (label it CRUD order when verbs are the only evidence):

```
CHAIN DOCUMENT — 7 steps
Step 1 · POST /ms-consumer/v1/user/document/upload  [NEW]
  Uploads one or more documents for the caller.
  Inputs needed: files (MultipartFile[]), docTypeId (Integer)
  curl -sS -X POST '${NEW_BASE}/ms-consumer/v1/user/document/upload' \
    -H "Authorization: Bearer ${TOKEN}" -F 'files=@{file}' -F 'docTypeId={docTypeId}'
Step 2 · GET /ms-consumer/v1/user/document/glove-dashboard  [NEW]
  UNKNOWN — no @Operation/javadoc on this handler
  No input needed — runnable as-is
  curl -sS -X GET '${NEW_BASE}/ms-consumer/v1/user/document/glove-dashboard' \
    -H "Authorization: Bearer ${TOKEN}"
```

Curl side: NEW when the row exists in new, OLD when `Missing in new`;
tag every step `[NEW]` or `[OLD]`. Cross-step ids (`{documentId} comes
from step 1 response`) only when code shows the create returns it.

## Never truncate paths

Old request path, New request path, Old curl, and New curl must show
the **full** string. Forbidden: `...`, CSS `text-overflow: ellipsis`,
`overflow: hidden` on path cells, substring/slice of a URL. Wrap instead.

OLD_BASE (default `https://www.way.com` — the `www` host; the apex 301s to www and curl strips Authorization on that cross-host hop, prefilled as the input `value`), NEW_BASE (default `https://newdev.way.com`), TOKEN (password input, never persisted), search, old-source filter, Copy per curl, Download CSV, Clear filters.

`fill()` / Copy rules (mandatory in the HTML JS):

- If OLD_BASE host is `way.com` (apex), rewrite to `https://www.way.com` before substituting. Never copy an apex old curl.
- If TOKEN input is empty, leave the literal `${TOKEN}` in the copied curl — never emit `Authorization: Bearer ` (empty). Empty Bearer on JWT rows returns 401 `"Full authentication is required"` and is **not** a missing `/security/userProfileManagement` path.
- Never emit `--location` / `-L` on old prod curls (cross-host 301 strips Authorization).
- Never rewrite `/v1/vehicle-services/...` (or any other literal class mapping) to insert `/security/userProfileManagement`.

Worked miss: user curl
`https://way.com/way-consumer/v1/vehicle-services/subscriptions`
with `--location` and empty Bearer → 401. Correct copy from the sheet:
`https://www.way.com/way-consumer/v1/vehicle-services/subscriptions`
plus a real token. Path is already full (HARD RULE 17).

Column filters (mandatory): a second sticky `<thead>` row. Selects for
Method, PRD match, Old source, Status, Auth, Data input, Validation,
Co-dependent chain, Logic match?, DB data verified?
(options = distinct values in this sheet + All). Text contains for
What this API does, Expected behaviour (PRD), Old path, New path,
Required inputs, Controllers, Use case, Old DB logic, New DB logic,
Missing / changed in new, Tables missing in newdev, Tables new vs old.
AND with the tab + search. Clear filters resets all of them. CSV and
Copy visible use the same filtered rows.

Download CSV must include **What this API does**, **Expected behaviour (PRD)**,
**PRD match**, and the eight appended SQL/logic columns. Search box must match
those columns too.
In-page CSV `a.download` uses the same timestamped basename as the HTML
file (not a fixed `<module>-old-new-curl-comparison.csv`).

## Report shell (copy it, do not redesign it)

Presentation is part of the deliverable — see STEP LOOK in SKILL.md. The
structure below is what the ms-consumer and ms-search reports ship, and
the next run should reuse the same CSS/JS rather than invent a skin:

```
<header>      repos + HEADs + context-paths, auth rule with file:line,
              plus <details class=verified> (collapsed) holding the
              plain-English "what was and was not verified" paragraphs
<div class=bar>   sticky OLD_BASE / NEW_BASE / TOKEN / Search /
                  Clear filters / Download CSV / row count
<div class=tabs>  pills
<table>       table-layout:fixed, per-column width, sticky 2 header rows
<div id=chains>   chain cards (hidden unless the Chains tab is active)
<script>      const DATA = {rows:[...], chains:{...}}; render from JS
```

Layout contract — 25 fixed-width columns only stay readable if all of
these hold together (see STEP LOOK 4, and verify in STEP EYES):

```css
body {width:max-content; min-width:100%}   /* sticky bar spans x-scroll */
h1, .meta, .verified {max-width:1180px}    /* header text stays left */
.wrap {padding:0 22px 40px}                /* NO overflow-x here */
table {table-layout:fixed; width:<sum of column widths>px; min-width:100%}
thead tr:first-child  th {position:sticky; top:var(--stick)}
thead tr:nth-child(2) th {position:sticky; top:var(--stick2)}
td .c, pre, .sqlbox {max-height:172px; overflow:auto}
```

`--stick` = measured `.bar` + `.tabs` height, `--stick2` = that plus the
measured header-row height; set both on load and on `resize`. `.tabs`
sits at `top:var(--barh)`. Never hardcode these offsets.

`<div class="c">` wraps the long prose cells — What this API does,
Expected behaviour (PRD), Required inputs, Use case, Missing / changed
in new, Tables missing in newdev, Tables new vs old.

CSS contract: `.badge` + `.b-both` (green) `.b-moved` (blue) `.b-miss`
(red) `.b-new` (amber) `.b-unk` / `.b-na` (grey) `.b-part` (amber);
`pre` for curls with a floating `.copy` button; `.sqlbox` scrollable for
SQL; `.sub` for the reason under a badge; `.warn` amber for
"DB data verified?"; `td.path` monospace. No `text-overflow: ellipsis`
anywhere. A scrollable `max-height` box is not clipping — the full text
is in the DOM and in the CSV; `ellipsis` throws the text away.

ROWS JSON fields (mandatory): `verb`, `what`, `prd_expected`,
`prd_match`, `prd_url` (Confluence URL or empty), `origin`, `old_path`,
`new_path`, `old_curl`, `new_curl`, `status`, `auth`, `data_input`,
`validation`, `required`, `chain`, `chain_members`, `links`
(`[[label, blob-url], …]`), `note`, `use_case`, `old_logic`,
`new_logic`, `logic_match`, `logic_match_cat`, `logic_missing`,
`tables_missing_newdev`, `tables_new_vs_old`, `db_verified`, `sql_gap`.
`prd_match` ∈ Match|Partial|Gap|UNKNOWN. `logic_match_cat` is the badge
value, `logic_match` the sentence under it.

CHAINS JSON: `{ "<CHAIN-ID>": { "evidence": "<code proof the steps
belong together, with file:line>", "steps": [ {n, title, side, what,
inputs, curl} ] } }`. A chain needs that evidence line before it may
exist — sibling endpoints in one controller are **not** a chain. Two
GETs that merely live in the same class are `None`; a writer/reader pair
documented in a service javadoc is a chain, and the step that must run
first says so in its `inputs` line.

## Chat

Paste the absolute HTML path. Do not dump the full table in markdown.
If the user pasted a failing curl, cite controller file:line + their
HTTP status, then the HTML path — do not invent a passing result.

Every cell is from opened code or an opened Service Rewrites PRD
(folder 43057153). Else `UNKNOWN`. End the chat with STEP SELF-ASSESS
from SKILL.md (scorecard). Do not add the scorecard as an HTML column.
