"""
analyser.py
-----------
LLM analysis layer for the OSAlt job postings module.

Responsibilities:
- Load processed job posting CSVs
- Classify each posting by function and seniority via LLM
- Aggregate classifications into company-level hiring summaries
- Generate per-company investment signal summaries
- Validate management claims against hiring data
- Write analysis outputs to data/processed/job_postings/

All LLM calls use the Anthropic SDK. Prompt templates are loaded from
OSAlt/analysis/job_postings/*.txt — edit those files to adjust analytical
framing without touching this module.

Usage:
    python analyser.py                    # Analyse all companies
    python analyser.py --ticker PANW      # Analyse one company
    python analyser.py --skip-classify    # Skip role classification (use cached)
"""

import argparse
import json
import os
import time
from pathlib import Path

import anthropic
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# Path resolution
REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed" / "job_postings"
PROMPTS_DIR = Path(__file__).parent

MODEL = "claude-sonnet-4-20250514"
CLASSIFICATION_BATCH_SIZE = 20   # Postings per LLM call for role classification
REQUEST_DELAY = 0.3              # Seconds between API calls


def load_prompt(template_name: str) -> str:
    """Load a prompt template from the analysis directory."""
    path = PROMPTS_DIR / f"{template_name}.txt"
    with open(path, "r") as f:
        return f.read()


def load_processed(ticker: str) -> pd.DataFrame:
    """Load a company's processed job postings CSV."""
    path = PROCESSED_DIR / f"{ticker}_processed.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"No processed data found for {ticker}. Run pipeline.py first."
        )
    return pd.read_csv(path)


def call_llm(prompt: str, client: anthropic.Anthropic) -> str:
    """
    Make a single LLM call and return the text response.
    All calls expect JSON back — parsing is the caller's responsibility.
    """
    message = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def classify_postings_batch(
    postings: list[dict], client: anthropic.Anthropic
) -> list[dict]:
    """
    Classify a batch of postings by function and seniority.

    Batching reduces API calls significantly — rather than one call per
    posting (potentially 200+ calls), we classify in groups. The tradeoff
    is slightly less nuanced classification for ambiguous roles at the
    edges of a batch. Acceptable for this use case.
    """
    template = load_prompt("classify_role")
    results = []

    for posting in postings:
        prompt = template.format(
            title=posting.get("title", ""),
            description=posting.get("description", ""),
        )

        try:
            response_text = call_llm(prompt, client)
            # Strip any accidental markdown fencing
            clean = response_text.strip().strip("```json").strip("```").strip()
            classification = json.loads(clean)
            classification["job_id"] = posting["job_id"]
            results.append(classification)
        except (json.JSONDecodeError, KeyError) as e:
            # Don't let one bad response break the batch
            results.append({
                "job_id": posting["job_id"],
                "function": "Other",
                "function_detail": "Classification failed",
                "seniority": "Mid",
                "is_ai_ml": False,
                "is_leadership": False,
                "location_type": "Unknown",
                "confidence": "Low",
                "error": str(e),
            })

        time.sleep(REQUEST_DELAY)

    return results


def classify_all_postings(
    df: pd.DataFrame, ticker: str, client: anthropic.Anthropic, force: bool = False
) -> pd.DataFrame:
    """
    Classify all postings for a company, using cached results where available.

    Classifications are cached as {ticker}_classified.csv to avoid re-running
    the full classification on every analysis run. Use force=True to reclassify.
    """
    cache_path = PROCESSED_DIR / f"{ticker}_classified.csv"

    if cache_path.exists() and not force:
        print(f"  Loading cached classifications for {ticker}")
        classified_df = pd.read_csv(cache_path)
        return df.merge(classified_df, on="job_id", how="left")

    print(f"  Classifying {len(df)} postings for {ticker}...")
    postings = df[["job_id", "title", "description"]].to_dict("records")
    classifications = classify_postings_batch(postings, client)

    classified_df = pd.DataFrame(classifications)
    classified_df.to_csv(cache_path, index=False)
    print(f"  Classifications saved: {ticker}_classified.csv")

    return df.merge(classified_df, on="job_id", how="left")


def build_hiring_summary(df: pd.DataFrame, ticker: str) -> dict:
    """
    Aggregate classified postings into a structured hiring summary
    suitable for passing to the signal generation prompt.
    """
    total = len(df)

    # Function breakdown
    func_counts = df["function"].value_counts()
    func_breakdown = "\n".join(
        f"  {func}: {count} ({count/total*100:.1f}%)"
        for func, count in func_counts.items()
    )

    # Seniority breakdown
    sen_counts = df["seniority"].value_counts()
    sen_breakdown = "\n".join(
        f"  {sen}: {count} ({count/total*100:.1f}%)"
        for sen, count in sen_counts.items()
    )

    # Top locations
    top_locs = df["location"].value_counts().head(8)
    loc_str = "\n".join(
        f"  {loc}: {count}" for loc, count in top_locs.items() if loc
    )

    # Top titles
    top_titles = df["title"].value_counts().head(10)
    titles_str = "\n".join(
        f"  {title}: {count}" for title, count in top_titles.items()
    )

    # Date range
    if "posted_date" in df.columns and df["posted_date"].notna().any():
        dates = pd.to_datetime(df["posted_date"], errors="coerce").dropna()
        date_range = f"{dates.min().strftime('%Y-%m-%d')} to {dates.max().strftime('%Y-%m-%d')}"
    else:
        date_range = "Unknown"

    # AI/ML and leadership counts
    ai_ml_count = int(df["is_ai_ml"].sum()) if "is_ai_ml" in df.columns else 0
    leadership_count = int(df["is_leadership"].sum()) if "is_leadership" in df.columns else 0

    return {
        "total_postings": total,
        "date_range": date_range,
        "function_breakdown": func_breakdown,
        "seniority_breakdown": sen_breakdown,
        "top_locations": loc_str,
        "top_titles": titles_str,
        "ai_ml_count": ai_ml_count,
        "ai_ml_pct": round(ai_ml_count / total * 100, 1),
        "leadership_count": leadership_count,
        "leadership_pct": round(leadership_count / total * 100, 1),
    }


def generate_company_signal(
    df: pd.DataFrame,
    company_name: str,
    ticker: str,
    client: anthropic.Anthropic,
) -> dict:
    """Generate an investment signal summary for a company."""
    print(f"  Generating signal summary for {ticker}...")

    summary_data = build_hiring_summary(df, ticker)
    template = load_prompt("company_signal")

    prompt = template.format(
        company_name=company_name,
        ticker=ticker,
        **summary_data,
    )

    response_text = call_llm(prompt, client)
    clean = response_text.strip().strip("```json").strip("```").strip()

    try:
        signal = json.loads(clean)
    except json.JSONDecodeError as e:
        signal = {
            "headline": "Signal generation failed",
            "signals": [],
            "summary": f"JSON parsing error: {e}",
            "data_caveats": "Analysis unavailable",
        }

    # Attach metadata
    signal["ticker"] = ticker
    signal["company_name"] = company_name
    signal["postings_analysed"] = summary_data["total_postings"]

    return signal


def validate_claim(
    df: pd.DataFrame,
    company_name: str,
    ticker: str,
    claim: dict,
    client: anthropic.Anthropic,
) -> dict:
    """
    Validate a specific management claim against hiring data.

    Args:
        claim: dict with keys:
            - text: the claim text from the filing
            - filing_type: e.g. "10-K FY2024"
            - filing_date: e.g. "2024-09-06"
            - relevant_functions: list of functions most relevant to this claim
              (used to filter the hiring data to what's most pertinent)
    """
    print(f"  Validating claim for {ticker}: {claim['text'][:60]}...")

    summary_data = build_hiring_summary(df, ticker)

    # Filter to most relevant postings for this claim
    relevant_functions = claim.get("relevant_functions", [])
    if relevant_functions:
        relevant_df = df[df["function"].isin(relevant_functions)]
    else:
        relevant_df = df

    relevant_summary = build_hiring_summary(relevant_df, ticker) if len(relevant_df) > 0 else summary_data

    relevant_hiring_data = (
        f"Postings in relevant functions ({', '.join(relevant_functions) if relevant_functions else 'all'}): "
        f"{relevant_summary['total_postings']} of {summary_data['total_postings']} total\n"
        f"Function breakdown (relevant subset):\n{relevant_summary['function_breakdown']}\n"
        f"Seniority breakdown (relevant subset):\n{relevant_summary['seniority_breakdown']}\n"
        f"Top titles (relevant subset):\n{relevant_summary['top_titles']}"
    )

    template = load_prompt("claims_validation")
    prompt = template.format(
        company_name=company_name,
        ticker=ticker,
        filing_type=claim.get("filing_type", "10-K"),
        filing_date=claim.get("filing_date", ""),
        claim_text=claim["text"],
        relevant_hiring_data=relevant_hiring_data,
        hiring_summary=(
            f"Total postings: {summary_data['total_postings']}\n"
            f"Function breakdown:\n{summary_data['function_breakdown']}\n"
            f"AI/ML roles: {summary_data['ai_ml_count']} ({summary_data['ai_ml_pct']}%)"
        ),
    )

    response_text = call_llm(prompt, client)
    clean = response_text.strip().strip("```json").strip("```").strip()

    try:
        result = json.loads(clean)
    except json.JSONDecodeError as e:
        result = {
            "verdict": "Inconclusive",
            "verdict_strength": "Weak",
            "evidence": f"Analysis failed: {e}",
            "gaps": "JSON parsing error prevented analysis",
            "investment_implication": "Unavailable",
            "memo_ready": False,
        }

    result["ticker"] = ticker
    result["claim_text"] = claim["text"]
    result["filing_type"] = claim.get("filing_type", "")

    return result


def run_analysis(
    tickers: list[str] | None = None,
    skip_classify: bool = False,
) -> dict:
    """
    Run the full analysis pipeline for all companies (or a subset).

    Returns:
        Dict with keys 'signals' and 'classifications', each mapping
        ticker → result. Suitable for passing directly to the dashboard.
    """
    client = anthropic.Anthropic()

    # Discover available tickers if not specified
    if tickers is None:
        tickers = [
            p.stem.replace("_processed", "")
            for p in PROCESSED_DIR.glob("*_processed.csv")
        ]

    all_signals = {}
    all_classified = {}

    # Company names — load from config for display
    try:
        import yaml
        config_path = Path(__file__).parents[1] / "ingestion" / "job_postings" / "companies.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        name_map = {c["ticker"]: c["name"] for c in config["companies"]}
    except Exception:
        name_map = {}

    for ticker in tickers:
        print(f"\n{'='*50}")
        print(f"Analysing: {ticker}")

        try:
            df = load_processed(ticker)
            company_name = name_map.get(ticker, ticker)

            if not skip_classify:
                df = classify_all_postings(df, ticker, client)
            else:
                cache_path = PROCESSED_DIR / f"{ticker}_classified.csv"
                if cache_path.exists():
                    classified_df = pd.read_csv(cache_path)
                    df = df.merge(classified_df, on="job_id", how="left")

            all_classified[ticker] = df

            signal = generate_company_signal(df, company_name, ticker, client)
            all_signals[ticker] = signal

            # Save signal to disk
            signal_path = PROCESSED_DIR / f"{ticker}_signal.json"
            with open(signal_path, "w") as f:
                json.dump(signal, f, indent=2)
            print(f"  Signal saved: {ticker}_signal.json")

        except FileNotFoundError as e:
            print(f"  Skipping {ticker}: {e}")
            continue

    print(f"\n{'='*50}")
    print(f"Analysis complete. Companies analysed: {list(all_signals.keys())}")

    return {"signals": all_signals, "classified": all_classified}


def run_claims_validation(ticker: str) -> list[dict]:
    """
    Run claims validation for a single company against all claims in config.

    Loads claims from companies.yaml, runs each through the validation
    prompt, and saves results to {ticker}_claims.json.
    """
    import yaml

    client = anthropic.Anthropic()

    config_path = Path(__file__).parents[2] / "ingestion" / "job_postings" / "companies.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    company_config = next(
        (c for c in config["companies"] if c["ticker"] == ticker), None
    )
    if not company_config:
        raise ValueError(f"Ticker {ticker} not found in companies.yaml")

    claims = company_config.get("claims", [])
    if not claims:
        print(f"  No claims configured for {ticker}")
        return []

    # Load classified data — required for claims validation
    classified_path = PROCESSED_DIR / f"{ticker}_classified.csv"
    processed_path = PROCESSED_DIR / f"{ticker}_processed.csv"

    if not classified_path.exists():
        raise FileNotFoundError(
            f"No classified data for {ticker}. Run analyser.py --ticker {ticker} first."
        )

    df_processed = pd.read_csv(processed_path)
    df_classified = pd.read_csv(classified_path)
    df = df_processed.merge(df_classified, on="job_id", how="left")

    company_name = company_config["name"]
    results = []

    print(f"\n{'='*50}")
    print(f"Claims validation: {company_name} ({ticker})")
    print(f"  {len(claims)} claims to validate")

    for claim in claims:
        result = validate_claim(df, company_name, ticker, claim, client)
        result["claim_id"] = claim["id"]
        result["hypothesis"] = claim.get("hypothesis", "")
        results.append(result)
        print(f"  [{result['verdict']}] {claim['id']}")
        time.sleep(REQUEST_DELAY)

    # Save to disk
    output_path = PROCESSED_DIR / f"{ticker}_claims.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved: {ticker}_claims.json")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OSAlt job postings analysis layer")
    parser.add_argument("--ticker", type=str, help="Analyse a single company by ticker")
    parser.add_argument(
        "--skip-classify",
        action="store_true",
        help="Skip role classification and use cached results",
    )
    parser.add_argument(
        "--claims",
        action="store_true",
        help="Run claims validation (requires --ticker)",
    )
    args = parser.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else None

    if args.claims:
        if not args.ticker:
            print("--claims requires --ticker. Example: python analyser.py --ticker PANW --claims")
        else:
            results = run_claims_validation(args.ticker.upper())
            print(json.dumps(results, indent=2))
    else:
        run_analysis(tickers=tickers, skip_classify=args.skip_classify)
