"""SEC EDGAR submissions collector for tracked companies.

Uses the public submissions JSON endpoint:
  https://data.sec.gov/submissions/CIK0000XXXXXX.json
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from intel.collectors.base import http_client

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}/{primary}"


def fetch_filings(cik: str, *, forms: tuple[str, ...] = ("10-K", "10-Q", "8-K", "S-1", "20-F")) -> Iterable[dict]:
    cik = cik.zfill(10)
    cik_int = int(cik)
    url = SUBMISSIONS_URL.format(cik=cik)
    with http_client() as client:
        # SEC requires a real-looking UA with contact; we keep it generic but include "research".
        resp = client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
    recent = data.get("filings", {}).get("recent", {})
    accs = recent.get("accessionNumber", [])
    forms_list = recent.get("form", [])
    dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    for acc, form, date_str, primary in zip(accs, forms_list, dates, primary_docs):
        if form not in forms:
            continue
        try:
            filed_at = datetime.fromisoformat(date_str)
        except ValueError:
            filed_at = datetime.utcnow()
        accession_no_dashes = acc.replace("-", "")
        url = ARCHIVE_URL.format(cik_int=cik_int, accession_no_dashes=accession_no_dashes, primary=primary)
        yield {
            "accession": acc,
            "form": form,
            "filed_at": filed_at,
            "url": url,
            "title": f"{form} - {primary}",
        }
