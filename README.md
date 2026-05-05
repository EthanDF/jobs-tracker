# jobs-tracker

Scrapes configured job listing sites daily and sends an email digest of new postings. Runs automatically via GitHub Actions every morning at 8:00 AM ET.

## How it works

The scraper checks each configured site for job listings, compares them against the last known state, and emails only the new ones. State is persisted in the `state/` directory and committed back to the repo after each run.

## Tracked sites

- **Union Jobs - Florida**
- **Progressive Data Jobs**
- **Tech Jobs for Good**

## Setup

### GitHub Actions (production)

Add the following secrets to your repository (Settings → Secrets → Actions):

- `EMAIL_SENDER` — Gmail address used to send the digest
- `EMAIL_PASSWORD` — Gmail app password
- `EMAIL_RECIPIENT` — Address to receive the digest

The workflow runs daily and can also be triggered manually from the Actions tab.

### Local development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
EMAIL_SENDER=x EMAIL_PASSWORD=x EMAIL_RECIPIENT=x python scraper.py
```

## Adding a new site

Add an entry to `config.json`:

```json
{
  "name": "Site Name",
  "url": "https://example.com/jobs/",
  "base_url": "https://example.com",
  "job_link_pattern": "/jobs/",
  "id_source": "slug",
  "state_file": "state/sitename.json"
}
```

**`id_source` options:**
- `query` (default) — extracts a numeric ID from `?id=123`
- `slug` — uses the last path segment (e.g. `/jobs/some-title/`)
- `numeric_slug` — same as slug but filters out non-numeric segments

**Optional fields:**
- `title_css_class` — CSS class of the element containing the job title within the link
- `employer_css_class` — CSS class of the element containing the employer name
