"""
pipeline.py
-----------
Orchestrates the full job postings ingestion pipeline for OSAlt.

Responsibilities:
- Load company config from companies.yaml
- Check local cache before making API calls
- Fetch raw data via AdzunaClient
- Filter results to confirmed company matches
- Normalise fields into a consistent schema
- Write raw (JSON) and processed (CSV) outputs to data directories
- Track request counts to stay within daily API limits

Data flow:
    companies.yaml
        → AdzunaClient.search_all_pages()
            → filter_results()
                → normalise_results()
                    → data/raw/job_postings/{ticker}_raw.json
                    → data/processed/job_postings/{ticker}_processed.csv
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

from adzuna_client import AdzunaClient

# Resolve paths relative to the repo root, regardless of where this script runs
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).parent / "companies.yaml"
RAW_DIR = REPO_ROOT / "data" / "raw" / "job_postings"
PROCESSED_DIR = REPO_ROOT / "data" / "processed" / "job_postings"


def load_config() -> dict:
    """Load and return the full companies.yaml config."""
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def is_cache_fresh(ticker: str, ttl_days: int) -> bool:
    """
    Return True if a cached raw file exists and is within the TTL window.
    Prevents redundant API calls on repeated pipeline runs.
    """
    cache_path = RAW_DIR / f"{ticker}_raw.json"
    if not cache_path.exists():
        return False

    modified_time = datetime.fromtimestamp(cache_path.stat().st_mtime)
    return datetime.now() - modified_time < timedelta(days=ttl_days)


def load_cached_raw(ticker: str) -> list[dict]:
    """Load raw results from local cache."""
    cache_path = RAW_DIR / f"{ticker}_raw.json"
    with open(cache_path, "r") as f:
        return json.load(f)


def save_raw(ticker: str, results: list[dict]) -> None:
    """Persist raw API results as JSON. Overwrites on refresh."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / f"{ticker}_raw.json"
    with open(cache_path, "w") as f:
        json.dump(results, f, indent=2)


def filter_results(results: list[dict], company_config: dict) -> list[dict]:
    """
    Filter raw Adzuna results to confirmed matches for a specific company.

    Validation logic (positive signal required, not exclusion-based):

    Primary: Company alias appears in the job description body. Genuine
    postings almost always contain the employer's own boilerplate — mission
    statements, culture copy, "who we are" sections. A third-party posting
    a partner/alliance role will contain their own boilerplate instead.
    This approach cleanly eliminates false positives like "Palo Alto Networks
    Business Development Leader" posted by IBM.

    Fallback: If the description is very short (under 200 characters, likely
    truncated before the employer name appears), accept the result if the
    company field matches a known alias. These are flagged for review.

    Note: Title matching is intentionally excluded from validation — the
    company name appearing in a job title is precisely what generates false
    positives (partner/alliance/channel roles at third-party employers).
    Title is used only at the query stage, not here.

    Exclusion: exclude_terms in config catch geographic false positives
    (e.g. "Palo Alto, CA" for PANW).
    """
    aliases = [a.lower() for a in company_config["adzuna_company_aliases"]]
    exclude_terms = [t.lower() for t in company_config.get("exclude_terms", [])]
    matched = []

    for job in results:
        company_field = job.get("company", {}).get("display_name", "").lower()
        title = job.get("title", "").lower()
        description = job.get("description", "").lower()

        # Primary: alias confirmed in description body
        description_match = any(alias in description for alias in aliases)

        # Fallback: short/truncated description but company field matches
        description_too_short = len(description) < 200
        company_field_match = any(alias in company_field for alias in aliases)
        fallback_match = description_too_short and company_field_match

        if not (description_match or fallback_match):
            continue

        # Apply geographic exclusion terms
        combined_text = f"{title} {description} {company_field}"
        if any(term in combined_text for term in exclude_terms):
            continue

        # Flag fallback matches for transparency in downstream analysis
        job["_filter_method"] = "fallback" if fallback_match else "description"

        matched.append(job)

    return matched


def normalise_results(results: list[dict], company_config: dict) -> pd.DataFrame:
    """
    Transform raw Adzuna result dicts into a clean, flat DataFrame.

    Schema:
        ticker          Company ticker symbol
        company_name    Canonical company name from config
        job_id          Adzuna's unique job identifier
        title           Job title as posted
        location        Location string (city, state where available)
        description     Full job description text (used by LLM analysis layer)
        salary_min      Minimum salary if provided (USD)
        salary_max      Maximum salary if provided (USD)
        posted_date     Date the posting was created (YYYY-MM-DD)
        redirect_url    Adzuna link to the posting
        retrieved_date  Date this pipeline run fetched the record
    """
    rows = []
    today = datetime.now().strftime("%Y-%m-%d")

    for job in results:
        # Location: Adzuna returns a nested dict; flatten to a readable string
        location_data = job.get("location", {})
        location_areas = location_data.get("area", [])
        location_str = ", ".join(location_areas) if location_areas else location_data.get("display_name", "")

        # Date: Adzuna returns ISO 8601 — truncate to date only
        created_raw = job.get("created", "")
        try:
            posted_date = datetime.fromisoformat(created_raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            posted_date = None

        rows.append({
            "ticker": company_config["ticker"],
            "company_name": company_config["name"],
            "job_id": job.get("id", ""),
            "title": job.get("title", ""),
            "location": location_str,
            "description": job.get("description", ""),
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "posted_date": posted_date,
            "redirect_url": job.get("redirect_url", ""),
            "retrieved_date": today,
            "filter_method": job.get("_filter_method", "description"),
        })

    return pd.DataFrame(rows)


def save_processed(ticker: str, df: pd.DataFrame) -> None:
    """Write processed DataFrame to CSV."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / f"{ticker}_processed.csv"
    df.to_csv(output_path, index=False)


def run_pipeline(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """
    Run the full ingestion pipeline for all companies in config.

    Args:
        force_refresh: If True, ignore cache and re-fetch all companies.

    Returns:
        Dict mapping ticker → processed DataFrame for downstream use
        (analysis layer, dashboard).
    """
    config = load_config()
    pipeline_cfg = config["pipeline"]
    companies = config["companies"]

    client = AdzunaClient()
    request_count = 0
    max_requests = pipeline_cfg["max_daily_requests"]
    results_by_ticker = {}

    for company in companies:
        ticker = company["ticker"]
        name = company["name"]

        print(f"\n{'='*50}")
        print(f"Processing: {name} ({ticker})")

        # Use cache if fresh and refresh not forced
        if not force_refresh and is_cache_fresh(ticker, pipeline_cfg["cache_ttl_days"]):
            print(f"  Cache is fresh — loading from disk")
            raw_results = load_cached_raw(ticker)
        else:
            # Check we have budget for this company's requests
            pages_needed = pipeline_cfg["max_pages"]
            if request_count + pages_needed > max_requests:
                print(f"  WARNING: Approaching daily request limit ({request_count}/{max_requests}). Skipping {name}.")
                continue

            print(f"  Fetching from Adzuna API...")
            raw_results = client.search_all_pages(
                query=company["adzuna_query"],
                country=pipeline_cfg["country"],
                results_per_page=pipeline_cfg["results_per_page"],
                max_pages=pipeline_cfg["max_pages"],
            )
            # Approximate: count pages actually fetched
            pages_fetched = -(-len(raw_results) // pipeline_cfg["results_per_page"])  # ceiling division
            request_count += pages_fetched

            save_raw(ticker, raw_results)
            print(f"  Fetched {len(raw_results)} raw results, saved to cache")

        # Filter to confirmed company matches
        filtered = filter_results(raw_results, company)
        print(f"  After filtering: {len(filtered)} confirmed matches (from {len(raw_results)} raw)")

        if len(filtered) == 0:
            print(f"  WARNING: No confirmed matches for {name}. Check aliases in companies.yaml.")
            continue

        # Normalise to DataFrame and persist
        df = normalise_results(filtered, company)
        save_processed(ticker, df)
        print(f"  Saved processed CSV: {ticker}_processed.csv")

        results_by_ticker[ticker] = df

        # Brief pause between companies to be a polite API consumer
        time.sleep(1)

    print(f"\n{'='*50}")
    print(f"Pipeline complete. API requests used: ~{request_count}/{max_requests}")
    print(f"Companies processed: {list(results_by_ticker.keys())}")

    return results_by_ticker


if __name__ == "__main__":
    run_pipeline()