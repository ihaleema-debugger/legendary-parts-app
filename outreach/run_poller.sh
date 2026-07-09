#!/bin/bash
#
# PYTHON RUNTIME NOTE (June 2026):
# This script intentionally uses system Python 3.14
# (/Library/Frameworks/Python.framework/Versions/3.14/bin/python3),
# NOT the project venv at keyword_forge/.venv.
#
# Reason: during June 2026 launchd/TCC debugging, the venv could not run
# reliably under launchd due to macOS permission restrictions. System Python
# 3.14 was the working solution that passed TCC checks.
#
# Consequence: any dependency the outreach poller needs must be pip-installed
# into system Python 3.14 directly, NOT into keyword_forge/.venv.
# Installing into the venv will silently not work when run via launchd.
#
# LIVE-GMAIL GATE (2026-07-09):
# outreach/gmail_client.py's get_gmail_service() refuses to authenticate
# unless OUTREACH_ALLOW_LIVE_GMAIL is set to the exact value below in the
# process's real environment. launchd does NOT inherit the interactive
# shell environment, so this cannot be set via ~/.zshrc or a manual export
# — it must be set here, inline, in the same place PYTHONPATH already is.
#
cd "/Users/mac/Documents/SEO Agent Workflow"
echo "POLLER CWD: $(pwd)"
ls -d "/Users/mac/Documents/SEO Agent Workflow" >/dev/null 2>&1 && echo "PROJECT DIR: readable" || echo "PROJECT DIR: NOT readable"
PYTHONPATH="/Users/mac/Documents/SEO Agent Workflow" OUTREACH_ALLOW_LIVE_GMAIL="i-know-this-hits-live-gmail" /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m outreach.poller
