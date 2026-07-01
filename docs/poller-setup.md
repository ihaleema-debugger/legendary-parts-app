# Outreach Poller — Python Runtime Setup

## What the poller uses and why

The launchd poller (`/Users/mac/bin/run_poller.sh`) intentionally uses **system
Python 3.14** (`/Library/Frameworks/Python.framework/Versions/3.14/bin/python3`)
rather than the project virtualenv at `keyword_forge/.venv`.

## Why not the venv?

During June 2026 launchd/TCC debugging, the venv Python consistently failed when
invoked by launchd. macOS TCC (Transparency, Consent, and Control) — the permission
layer that controls access to Mail, contacts, and other protected resources — would
block or sandbox the venv binary in ways it did not block the system-installed
Python. Switching to system Python 3.14 was the fix that allowed launchd to run the
poller reliably at 3pm daily without permission errors.

## What this means for dependencies

Any package the outreach poller depends on must be installed into **system Python
3.14**, not into the venv:

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/pip3 install <package>
```

Installing a package into `keyword_forge/.venv` will have **no effect** on the
poller. The venv is never activated by the launchd script, so its site-packages are
never on the path.

## If you rebuild or migrate

If you ever need to move the poller to a new machine or a new Python version, the
key things to replicate are:

1. The launchd plist at `~/Library/LaunchAgents/com.legendaryparts.outreach-poller.plist`
2. The wrapper script at `~/bin/run_poller.sh`
3. All poller dependencies installed into whichever Python binary the wrapper points at
4. The Gmail credentials in `outreach/secrets/` (gitignored — back up separately)
5. The outreach state database `outreach/outreach_state.db` (gitignored — back up separately)
