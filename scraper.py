#!/usr/bin/env python3
"""
jobs-tracker: Check configured job listing pages daily and email only new postings.
"""

import json
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CONFIG_FILE = "config.json"
USER_AGENT = "Mozilla/5.0 (compatible; jobs-tracker/1.0)"


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_state(state_file):
    path = Path(state_file)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_state(state_file, jobs):
    Path(state_file).parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(jobs, f, indent=2, sort_keys=True)


def fetch_jobs(site):
    """
    Generic fetcher: finds all <a> tags whose href contains job_link_pattern,
    extracts an ID from the URL, and captures the surrounding context as metadata.
    Works for any site that uses URL-based job IDs.
    """
    url = site["url"]
    base_url = site.get("base_url", "")
    pattern = site["job_link_pattern"]

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    # id_source controls how the unique job ID is extracted from the URL:
    #   "query" (default) — pulls the numeric id from ?id=123
    #   "slug"            — uses the last path segment (e.g. /job-posting/some-title/)
    id_source = site.get("id_source", "query")

    jobs = {}

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if pattern not in href:
            continue

        if id_source in ("slug", "numeric_slug", "numeric_prefix"):
            # Strip query string/fragment, then grab the last path component
            path = href.split("?")[0].split("#")[0]
            job_id = path.rstrip("/").rsplit("/", 1)[-1]
            if id_source == "numeric_slug" and not job_id.isdigit():
                continue
            if id_source == "numeric_prefix":
                # Extract leading number from slugs like "30280-job-title"
                m = re.match(r"^(\d+)-", job_id)
                if not m:
                    continue
                job_id = m.group(1)
        else:
            match = re.search(r"[?&]id=(\d+)", href)
            if not match:
                continue
            job_id = match.group(1)

        if not job_id:
            continue

        title_class = site.get("title_css_class")
        if title_class:
            title_el = a.find(class_=title_class)
            title = title_el.get_text(strip=True) if title_el else a.get_text(strip=True)
        else:
            title = a.get_text(strip=True)
        if not title:
            continue

        # Skip duplicate hrefs (e.g. a "View Job" button that shares the same href as the title)
        if job_id in jobs:
            continue

        # Capture surrounding li/td text for metadata (location, date, etc.)
        parent = a.find_parent(["li", "td", "div", "p"])
        meta = parent.get_text(" ", strip=True) if parent else ""

        # Try to find the employer: check for a configured CSS class first,
        # then fall back to nearby headings
        employer = ""
        employer_class = site.get("employer_css_class")
        if employer_class:
            el = (a.find_next(class_=employer_class) or a.find_previous(class_=employer_class))
            if el:
                employer = el.get_text(strip=True)
        if not employer:
            for tag in ["h3", "h2", "h4", "strong"]:
                heading = a.find_previous(tag)
                if heading:
                    employer = heading.get_text(strip=True)
                    break

        full_url = base_url + href if href.startswith("/") else href

        jobs[job_id] = {
            "title": title,
            "employer": employer,
            "url": full_url,
            "meta": meta,
        }

    return jobs


def build_email_body(site_name, site_url, new_jobs):
    lines = [
        f'<h2>New listings on <a href="{site_url}">{site_name}</a></h2>',
        "<ul>",
    ]
    for job in new_jobs.values():
        employer_prefix = f"<strong>{job['employer']}</strong> — " if job["employer"] else ""
        lines.append(
            f'  <li>{employer_prefix}<a href="{job["url"]}">{job["title"]}</a>'
            f'<br><small>{job["meta"]}</small></li>'
        )
    lines.append("</ul>")
    return "\n".join(lines)


def send_email(recipient, subject, html_body):
    sender = os.environ["EMAIL_SENDER"]
    password = os.environ["EMAIL_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())


def main():
    config = load_config()
    recipient = os.environ.get("EMAIL_RECIPIENT") or config.get("email_recipient")

    summary_lines = []
    email_sections = []

    for site in config["sites"]:
        name = site["name"]
        print(f"Checking: {name}")

        try:
            current_jobs = fetch_jobs(site)
        except Exception as e:
            print(f"  ERROR fetching {name}: {e}", file=sys.stderr)
            summary_lines.append(f"<li><strong>{name}</strong>: ERROR — {e}</li>")
            continue

        print(f"  Found {len(current_jobs)} total listings")

        previous_jobs = load_state(site["state_file"])
        new_jobs = {jid: job for jid, job in current_jobs.items() if jid not in previous_jobs}

        print(f"  {len(new_jobs)} new listings")

        site_link = f'<a href="{site["url"]}">{name}</a>'
        if new_jobs:
            summary_lines.append(
                f"<li><strong>{site_link}</strong>: {len(new_jobs)} new listing(s)</li>"
            )
            email_sections.append(build_email_body(name, site["url"], new_jobs))
        else:
            summary_lines.append(
                f"<li><strong>{site_link}</strong>: no new listings</li>"
            )

        save_state(site["state_file"], current_jobs)

    # Always send a daily digest
    has_new = any("new listing(s)" in line for line in summary_lines)
    subject = (
        "[jobs-tracker] New listings found"
        if has_new
        else "[jobs-tracker] No new listings today"
    )

    body_parts = [
        "<h2>Daily jobs-tracker summary</h2>",
        "<ul>",
        *summary_lines,
        "</ul>",
    ]
    if email_sections:
        body_parts.append("<hr>")
        body_parts.extend(email_sections)

    body = "\n".join(body_parts)

    try:
        send_email(recipient, subject, body)
        print(f"Summary email sent to {recipient}")
    except Exception as e:
        print(f"ERROR sending summary email: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
