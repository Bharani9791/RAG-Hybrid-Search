# Migrate VSession Server Script

## Purpose

This script migrates `VSession.server` (and `session_id` where applicable) between
Vonage-style and OpenVidu-style values for eligible **future scheduled** sessions
**for a single provider** (`vsessions.prov_id` = `--provider-id`). Optionally you can
limit rows to sessions **created by** specific client contacts via
`--client-emails` (see below). It writes
structured logs to the console and to a log file so operators can audit what would
change (dry run) or what was changed (apply).

**Script path (from repo root):** `scripts/python/migrate_vsession_server.py`

Run as a module so relative imports (`script_utils`) resolve:

```bash
poetry run python -m scripts.python.migrate_vsession_server ...
```

## Eligibility filters

A row is migrated only when **all** of the following are true:

| Filter | Meaning |
|--------|---------|
| `scheduled_at > now` (UTC) | Session is scheduled in the future (`get_utc_now()`). |
| `started_at IS NULL` | Call has not started. |
| `ended_at IS NULL` | Call has not ended. |
| `call_type == SCHEDULED` | Scheduled call type (`SCHEDULED` constant). |
| `state IN (...)` | `interpreter_sourced` or `no_interpreter_sourced` (`INTERPRETER_SOURCED_STATE`, `NO_INTERPRETER_SOURCED_STATE`). |
| `vsessions.prov_id` | Must equal **`--provider-id`** (`providers.prov_id`). |
| `vsession_created_by` | If **`--client-emails`** is set: `created_by_id` must be one of the resolved `contacts.cont_id` rows for those emails **and** the same `prov_id`. Sessions with no matching creator are out of scope. |

Additional filters depend on migration direction (see below).

Base query (then direction-specific `server` filters are applied):

```python
q = db.session.query(VSession).filter(
    VSession.scheduled_at > get_utc_now(),
    VSession.started_at.is_(None),
    VSession.ended_at.is_(None),
    VSession.call_type == SCHEDULED,
    VSession.state.in_(
        (
            INTERPRETER_SOURCED_STATE,
            NO_INTERPRETER_SOURCED_STATE,
        )
    ),
    VSession.prov_id == provider_id,
)
if created_by_contact_ids is not None:
    q = q.filter(VSession.created_by_id.in_(created_by_contact_ids))
```

`--provider-id` is validated before the query:

```python
def _validate_provider_id(provider_id: int) -> None:
    if provider_id <= 0:
        _fail("--provider-id must be a positive integer (not 0).")
    if db.session.query(Provider.id).filter(Provider.id == provider_id).first() is None:
        _fail(f"No provider row for prov_id={provider_id}.")
```

## CLI arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--video_provider_from` | Yes | `vonage` or `openvidu` (case-insensitive). |
| `--video_provider_to` | Yes | Must be the opposite direction: vonage → openvidu, or openvidu → vonage. |
| `--provider-id` | Yes | `providers.prov_id`: only sessions with this `vsessions.prov_id` are in scope. Must be **> 0** and must **exist** in `providers`. |
| `--dry-run` | No | Log planned changes only; **no** database updates. |
| `--client-emails` | No | Comma-separated client login emails (`contacts.cont_login_email`), e.g. `client1@gmail.com, client2@gmail.com`. Matching is **case-insensitive**; spaces around commas are trimmed. Only sessions whose **`created_by_id`** points to a contact with one of those emails **for the same `--provider-id`** are migrated. **Every** listed email must resolve to at least one contact; otherwise the script exits with code `1`. If omitted, **all** eligible sessions for the provider are considered (no filter on creator). |

Parser definition:

```python
parser.add_argument("--video_provider_from", required=True, ...)
parser.add_argument("--video_provider_to", required=True, ...)
parser.add_argument("--provider-id", type=int, required=True, metavar="PROV_ID", ...)
parser.add_argument("--dry-run", action="store_true", ...)
parser.add_argument("--client-emails", metavar="EMAIL_LIST", default=None, ...)
```

Direction is normalized and checked before any database writes:

```python
video_provider_from = args.video_provider_from.strip().lower()
video_provider_to = args.video_provider_to.strip().lower()
supported_providers = {"vonage", "openvidu"}

if video_provider_from not in supported_providers:
    _fail("Unsupported provider. Use 'vonage' or 'openvidu'.")
if video_provider_to not in supported_providers:
    _fail("Unsupported target provider. Use 'vonage' or 'openvidu'.")
if video_provider_from == video_provider_to:
    _fail(
        "video_provider_from and video_provider_to must differ; nothing to migrate."
    )

expected_target = "openvidu" if video_provider_from == "vonage" else "vonage"
if video_provider_to != expected_target:
    _fail(
        "Invalid migration direction. Expected --video_provider_to "
        f"'{expected_target}' for --video_provider_from '{video_provider_from}'."
    )
```

If validation fails (wrong providers, same from/to, invalid direction, **`--provider-id` ≤ 0 or unknown `prov_id`**, **no contact for a listed `--client-emails` address under that provider**, or missing
config such as `OPENVIDU_PUBLICURL` / Vonage keys), the script exits with code `1`.

### `--client-emails` resolution

Emails are split on commas, stripped, lowercased, and de-duplicated. Each address
must match `contacts.cont_login_email` for the same `--provider-id`:

```python
def _normalize_client_emails(raw: Optional[str]) -> list[str]:
    if raw is None or not raw.strip():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(","):
        norm = part.strip().lower()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _contact_ids_for_client_emails(emails: list[str], provider_id: int) -> list[int]:
    rows = (
        db.session.query(Contact.id, func.lower(Contact.email))
        .filter(
            Contact.provider_id == provider_id,
            func.lower(Contact.email).in_(emails),
        )
        .all()
    )
    found_lower = {email_lc for _, email_lc in rows}
    missing = [e for e in emails if e not in found_lower]
    if missing:
        _fail(
            "No contact for --provider-id=%s with cont_login_email matching: %s"
            % (provider_id, ", ".join(missing))
        )
    return sorted({row[0] for row in rows})
```

## Migration behavior

### `--video_provider_from vonage` → `--video_provider_to openvidu`

- **Extra filter:** `LOWER(server) LIKE 'vonage%'`.
- **Target `server`:** `ov.find_server()["OPENVIDU_PUBLICURL"]` (must be present).
- **Updates per row:**
  - `session.server` = OpenVidu public URL.
  - `session.session_id` = `"ses_" + gen_random_session_id()` (unique per row).

```python
q = q.filter(func.lower(VSession.server).like("vonage%"))
config = ov.find_server()
openvidu_server = config.get("OPENVIDU_PUBLICURL")
if not openvidu_server:
    _fail("OPENVIDU_PUBLICURL is missing; cannot migrate from vonage.")

sessions = q.all()
for session in sessions:
    old_server = session.server
    old_session_id = session.session_id
    if dry_run:
        new_sid_desc = "ses_<new unique random per row on apply>"
        # log planned server / session_id; no writes
    else:
        new_session_id = "ses_" + gen_random_session_id()
        session.server = openvidu_server
        session.session_id = new_session_id
```

Dry-run does **not** call `gen_random_session_id()`; the log shows a placeholder
for `session_id`. Apply generates a new id per row.

### `--video_provider_from openvidu` → `--video_provider_to vonage`

- **Extra filter:** `LOWER(server)` does **not** start with `vonage`.
- **Requires:** `BaseConfig.VIDEO_PROVIDER` and `BaseConfig.VONAGE_API_KEY`
  (presence check). The written `server` string uses the `VONAGE_VIDEO_PROVIDER`
  constant, not `BaseConfig.VIDEO_PROVIDER`.
- **Updates per row:**
  - `session.server` = `f"{VONAGE_VIDEO_PROVIDER}-{VONAGE_API_KEY}-{FLASK_ENV}"`.
  - `session.session_id` = `None`.

```python
q = q.filter(~func.lower(VSession.server).like("vonage%"))
if not BaseConfig.VIDEO_PROVIDER or not BaseConfig.VONAGE_API_KEY:
    _fail(
        "VIDEO_PROVIDER and VONAGE_API_KEY are required to migrate from openvidu."
    )
vonage_style_server = (
    f"{VONAGE_VIDEO_PROVIDER}-"
    f"{BaseConfig.VONAGE_API_KEY}-"
    f"{BaseConfig.FLASK_ENV}"
)

sessions = q.all()
for session in sessions:
    if not dry_run:
        session.server = vonage_style_server
        session.session_id = None
```

## Dry run (`--dry-run`)

- Runs the same query and logging as apply mode.
- Logs each matching row: snapshot fields (see **Logging**), then planned
  `server` and `session_id` changes.
- Does **not** execute `UPDATE` or `commit`.
- Ends with a dry-run summary line; no rows are modified.

```python
if dry_run:
    logger.info(
        "DRY-RUN COMPLETE | %s row(s) would be updated | no database changes made",
        count,
    )
    print(
        f"\nDry run finished: {count} row(s) would be updated. "
        f"See {LOG_PATH} for full detail.\n"
    )
    return

db.session.commit()
```

## Logging

- **Log file:** `migrate_vsession_server.log` at the **project root** (next to
  `pyproject.toml`), same pattern as `manage_db.py` / `db_operations.log`
  (`setup_logger` from `scripts/python/script_utils.py`).
- **Handlers:** file + console; format includes timestamp and level.

```python
LOG_FILENAME = "migrate_vsession_server.log"
LOG_PATH = os.path.join(_PROJECT_ROOT, LOG_FILENAME)

logger = setup_logger(
    name="migrate_vsession_server",
    log_file=LOG_PATH,
    file_format="%(asctime)s | %(levelname)-8s | %(message)s",
    console_format="%(levelname)s: %(message)s",
    date_format="%Y-%m-%d %H:%M:%S",
)
```

Per-row snapshot fields (model attribute names):

```python
_ROW_CONTEXT_FIELDS: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("session_id", "session_id"),
    ("session_name", "session_name"),
    ("scheduled_at", "scheduled_at"),
    ("scheduled_end", "scheduled_end"),
    ("state", "state"),
    ("server", "server"),
    ("started_at", "started_at"),
    ("ended_at", "ended_at"),
    ("created_by_id", "created_by_id"),
)
```

Typical content:

1. Banner: migration **from** / **to** video provider, mode (dry run vs apply), log
   path, **provider scope** (`prov_id`), command line (`argv`).
2. Eligibility summary (filters listed above, including `prov_id` and, when set,
   the **`created_by_id` / client-email** constraint).
3. If **`--client-emails`** is set: a line listing resolved
   `vsession_created_by IN (...)` (`contacts.cont_id` values).
4. Direction-specific plan (which columns change, resolved target `server` string).
5. For **each** matching row:
   - Record number (e.g. Record 1 of N), `id`, `session_name`.
   - **Row snapshot** (current DB values): `id`, `session_id`, `session_name`,
     `scheduled_at`, `scheduled_end`, `state`, `server`, `started_at`, `ended_at`,
     `created_by_id`.
   - **Changes:** `server` and `session_id` only — previous value → new value.
   - Footer: `[DRY-RUN]` or `[UPDATED]` as appropriate.
6. **Dry run:** `DRY-RUN COMPLETE` with count; **apply:** `COMMIT OK` with count.

## Transaction and error handling

- Work runs inside `FlaskAppManager()` (Flask app context).
- All updates run in **one** database transaction.
- On success (apply only): `db.session.commit()`.
- On exception: `db.session.rollback()`, error logged, exit code `1`.
- Success message on apply references the log file path.

```python
with FlaskAppManager():
    try:
        # query + per-row updates
        if dry_run:
            return
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("Migration failed; transaction rolled back")
        _fail(f"Migration failed and was rolled back: {exc}")
```

`_fail` always logs, prints to stderr, and exits with status `1`:

```python
def _fail(message: str) -> NoReturn:
    logger.error(message)
    print(message, file=sys.stderr)
    raise SystemExit(1)
```

## Usage

From the repository root (replace `42` with your `providers.prov_id`):

**Vonage → OpenVidu (dry run first):**

```bash
poetry run python -m scripts.python.migrate_vsession_server \
  --video_provider_from=vonage \
  --video_provider_to=openvidu \
  --provider-id=42 \
  --dry-run
```

**Same provider, only sessions created by listed client emails** (`created_by_id` → `contacts` for that `prov_id`):

```bash
poetry run python -m scripts.python.migrate_vsession_server \
  --video_provider_from=vonage \
  --video_provider_to=openvidu \
  --provider-id=42 \
  --client-emails="client1@gmail.com, client2@gmail.com" \
  --dry-run
```

**Same migration (apply):**

```bash
poetry run python -m scripts.python.migrate_vsession_server \
  --video_provider_from=vonage \
  --video_provider_to=openvidu \
  --provider-id=42
```

**OpenVidu → Vonage:**

```bash
poetry run python -m scripts.python.migrate_vsession_server \
  --video_provider_from=openvidu \
  --video_provider_to=vonage \
  --provider-id=42 \
  --dry-run
```

```bash
poetry run python -m scripts.python.migrate_vsession_server \
  --video_provider_from=openvidu \
  --video_provider_to=vonage \
  --provider-id=42
```

Ensure environment variables and `.env` are loaded so the Flask app, database,
and `ov.find_server()` / Vonage config resolve correctly when running the script.

## Related code

- `scripts/python/migrate_vsession_server.py` — full implementation
- `lvdispatch.models.vsession.VSession` — `server`, `session_id`, `prov_id`, `created_by_id`
- `lvdispatch.models.contact.Contact` — `email` (`cont_login_email`), `provider_id`
- `lvdispatch.ov.find_server` — OpenVidu `OPENVIDU_PUBLICURL`
- `lvdispatch.util.gen_random_session_id` — OpenVidu `session_id` suffix
- `lvdispatch.constants.VONAGE_VIDEO_PROVIDER` — Vonage `server` prefix

## Architecture Overview

Migration Workflow

Phase 1
Input Validation

Phase 2
Session Discovery

Phase 3
Direction Validation

Phase 4
Update Processing

Phase 5
Transaction Commit

## Troubleshooting Guide

Issue:
OPENVIDU_PUBLICURL missing

Cause:
Environment variable not found

Resolution:
Update configuration

Issue:
No contact found

Cause:
Email doesn't exist under provider

Resolution:
Validate client emails

Issue:
Transaction rollback

Cause:
Database exception

Resolution:
Review logs