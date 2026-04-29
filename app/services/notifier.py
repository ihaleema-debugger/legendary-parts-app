"""SMTP email notification after all translation tasks complete."""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_LANG_NAMES = {
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "sl": "Slovenian",
    "pt": "Portuguese",
}


def send_summary(
    original_slug: str,
    source_doc_id: str,
    results: list[dict],
) -> None:
    """Send the translation completion email.

    Args:
        original_slug: e.g. "harley-davidson-battery-guide"
        source_doc_id: Google Drive ID of the English source doc
        results: list of per-language result dicts:
            {
                "lang": str,
                "status": "success" | "failed",
                "doc_id": str | None,
                "doc_url": str | None,
                "flags": list[dict],  # validation + inline flags
                "error": str | None,
            }
    """
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    notify_email = os.environ.get("NOTIFY_EMAIL", smtp_user)

    if not all([smtp_host, smtp_user, smtp_password, notify_email]):
        raise RuntimeError(
            "SMTP is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, "
            "SMTP_PASSWORD, and NOTIFY_EMAIL in your .env file."
        )

    subject = f"[SEO-Forge] Translation complete: {original_slug}"
    plain, html = _build_body(original_slug, source_doc_id, results)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = notify_email
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [notify_email], msg.as_string())


def _build_body(original_slug: str, source_doc_id: str, results: list[dict]) -> tuple[str, str]:
    successes = sum(1 for r in results if r.get("status") == "success")
    total_flags = sum(len(r.get("flags", [])) for r in results if r.get("status") == "success")
    source_url = f"https://docs.google.com/document/d/{source_doc_id}/edit"

    # ── Plain text ────────────────────────────────────────────────────────────
    plain_lines = [
        f"SEO-Forge Translation Report: {original_slug}",
        "=" * 60,
        f"{successes} of {len(results)} translations succeeded. {total_flags} review flags raised.",
        "",
    ]
    for r in results:
        lang = r.get("lang", "?")
        lang_name = _LANG_NAMES.get(lang, lang.upper())
        if r.get("status") == "success":
            flags = r.get("flags", [])
            errors = sum(1 for f in flags if f.get("severity") == "error")
            warnings = sum(1 for f in flags if f.get("severity") == "warning")
            infos = sum(1 for f in flags if f.get("severity") == "info")
            plain_lines.append(
                f"{lang_name} ({lang.upper()}) ✓ — "
                f"{errors} error(s), {warnings} warning(s), {infos} info(s)"
            )
            plain_lines.append(f"  Doc: {r.get('doc_url', 'N/A')}")
        else:
            plain_lines.append(f"{lang_name} ({lang.upper()}) ✗ — {r.get('error', 'Unknown error')}")
        plain_lines.append("")

    plain_lines += ["", f"Source English doc: {source_url}"]
    plain = "\n".join(plain_lines)

    # ── HTML ──────────────────────────────────────────────────────────────────
    rows = []
    for r in results:
        lang = r.get("lang", "?")
        lang_name = _LANG_NAMES.get(lang, lang.upper())
        if r.get("status") == "success":
            flags = r.get("flags", [])
            errors = sum(1 for f in flags if f.get("severity") == "error")
            warnings = sum(1 for f in flags if f.get("severity") == "warning")
            infos = sum(1 for f in flags if f.get("severity") == "info")
            doc_url = r.get("doc_url", "#")
            flag_summary = f"{errors}E / {warnings}W / {infos}I"
            rows.append(
                f"<tr>"
                f"<td>{lang_name} ({lang.upper()})</td>"
                f"<td style='color:green'>✓ Success</td>"
                f"<td><a href='{doc_url}'>Open Doc</a></td>"
                f"<td>{flag_summary}</td>"
                f"</tr>"
            )
        else:
            err = r.get("error", "Unknown error")
            rows.append(
                f"<tr>"
                f"<td>{lang_name} ({lang.upper()})</td>"
                f"<td style='color:red'>✗ Failed</td>"
                f"<td colspan='2'>{err}</td>"
                f"</tr>"
            )

    table = (
        "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>"
        "<tr><th>Language</th><th>Status</th><th>Doc</th><th>Flags (E/W/I)</th></tr>"
        + "\n".join(rows)
        + "</table>"
    )

    html = f"""<html><body>
<h2>SEO-Forge Translation Report: {original_slug}</h2>
<p><strong>{successes} of {len(results)} translations succeeded. {total_flags} review flags raised.</strong></p>
{table}
<p>Source English doc: <a href="{source_url}">{source_doc_id}</a></p>
</body></html>"""

    return plain, html
