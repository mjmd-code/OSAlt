"""
adzuna_client.py
----------------
Thin wrapper around the Adzuna Jobs API.

Responsibilities:
- Construct and execute search requests
- Handle pagination
- Return raw API responses as Python dicts (no transformation here)
- Respect rate limits and surface errors clearly

All transformation and filtering logic lives in pipeline.py, not here.
"""

import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs"
DEFAULT_COUNTRY = "us"


class AdzunaClient:
    def __init__(self):
        self.app_id = os.getenv("ADZUNA_APP_ID")
        self.app_key = os.getenv("ADZUNA_APP_KEY")

        if not self.app_id or not self.app_key:
            raise EnvironmentError(
                "ADZUNA_APP_ID and ADZUNA_APP_KEY must be set in your .env file. "
                "Register at https://developer.adzuna.com to obtain credentials."
            )

    def search(
        self,
        query: str,
        country: str = DEFAULT_COUNTRY,
        page: int = 1,
        results_per_page: int = 50,
    ) -> dict:
        """
        Execute a single search request against the Adzuna API.

        Args:
            query:            Search string, passed to the `what` parameter.
                              Adzuna treats this as a phrase search against
                              job title and description.
            country:          Two-letter country code (default: "us").
            page:             Page number for pagination (1-indexed).
            results_per_page: Number of results to return (max 50).

        Returns:
            Raw API response as a dict. Caller is responsible for checking
            `response["count"]` and deciding whether to paginate.

        Raises:
            requests.HTTPError: On non-2xx responses.
            RuntimeError:       If the response cannot be parsed as JSON.
        """
        url = f"{ADZUNA_BASE_URL}/{country}/search/{page}"

        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "what": query,
            "results_per_page": results_per_page,
            "content-type": "application/json",
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        try:
            return response.json()
        except ValueError as e:
            raise RuntimeError(f"Failed to parse Adzuna response as JSON: {e}")

    def search_all_pages(
        self,
        query: str,
        country: str = DEFAULT_COUNTRY,
        results_per_page: int = 50,
        max_pages: int = 5,
        request_delay: float = 0.5,
    ) -> list[dict]:
        """
        Paginate through Adzuna results for a query, up to max_pages.

        The 0.5s delay between requests is conservative but respectful of
        Adzuna's free tier. At 5 pages per company and 5 companies, this
        adds ~12.5s to a full pipeline run — acceptable.

        Args:
            query:          Search string.
            country:        Two-letter country code.
            results_per_page: Max 50 (Adzuna hard limit).
            max_pages:      Hard cap on pages fetched. Prevents accidentally
                            burning the daily rate limit on one company.
            request_delay:  Seconds to wait between page requests.

        Returns:
            List of raw job result dicts from all pages combined.
        """
        all_results = []

        for page in range(1, max_pages + 1):
            response = self.search(
                query=query,
                country=country,
                page=page,
                results_per_page=results_per_page,
            )

            results = response.get("results", [])
            all_results.extend(results)

            # Stop paginating if this page returned fewer results than requested
            # — we've reached the end of available results
            if len(results) < results_per_page:
                break

            # Respect rate limits between page requests
            if page < max_pages:
                time.sleep(request_delay)

        return all_results
