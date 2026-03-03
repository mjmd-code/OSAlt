# OSAlt
Open-sourcing the world of alternative data

**Open-source alternative data methodology for investment research.**
OSAlt is a framework for systematically validating management claims and monitoring emerging risks using publicly available data sources and LLM-powered analysis. It is built on the premise that AI is rapidly eroding the moat around proprietary alternative data — and that a rigorous, reproducible open-source methodology can surface investment-relevant signal at a fraction of the cost of traditional data procurement.

---

## The Problem
Alternative data has historically been the preserve of well-resourced institutions. The barriers were threefold: acquisition cost, processing capability, and analytical expertise. AI is eroding all three simultaneously. OSAlt is an attempt to systematise what that erosion makes possible.

The starting point is not "what does this data tell me" — that's how you get a dashboard nobody uses. The starting point is a specific, testable claim: *management said X, does the evidence support it?*

---

## Methodology
1. **Claim extraction** — an LLM reads a company's 10-K and identifies specific management claims that are testable against public data, alongside flagged risks that may be crystallising
2. **Source mapping** — for each claim or risk, the framework identifies appropriate open-source datasets capable of validating or contradicting it
3. **Pipeline execution** — lightweight, reproducible data pipelines ingest and process the relevant sources
4. **Synthesis** — a second LLM layer assesses what the data says relative to what management said, and flags divergences
5. **Investment memo** — findings are structured as a written research output in standard investment format, connecting data to an investable thesis

### Planned analytical layers

**Guidance language change detection** — consecutive filings are diffed to identify subtle shifts in wording that precede guidance revisions. Extends the claim extraction layer with minimal additional architecture; the signal is in what changes between filings as much as what any single filing says.

**Management credibility scoring** — tracks historical forecasting accuracy and language consistency over time. Transforms OSAlt from a snapshot diligence tool into something with compounding value: a validated claim matters more or less depending on whether management has earned the benefit of the doubt.

### Speculative analytical layers

**Fraud and manipulation red flags** — accruals analysis, identification of serial "one-time" items, and linguistic risk flags combined into a forensic layer. Sits at the intersection of quantitative and qualitative signal. Technically tractable but methodologically complex; included here as a direction rather than a commitment.

---

## Data Sources

| Source | Signal type | Status |
|---|---|---|
| GitHub API | Engineering velocity, R&D intensity, open-source strategy | Planned |
| USASpending.gov | Public sector revenue validation | Planned |
| USPTO / EPO patent filings | R&D claims, technology pivots | Planned |
| UK/US planning applications | Physical footprint expansion claims | Planned |
| SEC EDGAR | Filing cross-reference and textual analysis | Planned |
| Public pricing pages | Pricing power claim validation | Speculative |

---

## Project Structure

```
OSAlt/
├── ingestion/          # Data pipeline modules by source
├── analysis/           # LLM prompt templates and analysis logic
├── dashboard/          # Streamlit interface
├── memos/              # Published investment research outputs
├── notebooks/          # Exploratory analysis and methodology development
└── README.md
```

---

## Current Status

Early-stage proof of concept. The first published output will apply the full methodology to a single company in a single sector, with pipelines built for two data sources. The memo will be included in `/memos`.

This is the beginning of a methodology, not a finished product. Contributions, feedback, and methodological critique are welcome.

---

## Setup

```bash
git clone https://github.com/[username]/osalt.git
cd osalt
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # add your API keys here
```

---

## Caveats

OSAlt is a research and methodology project. Nothing here constitutes investment advice. Pipeline robustness, data cleanliness, and historical coverage vary by source and are explicitly noted in each module. The goal is signal identification, not production-grade data infrastructure.

---

## License

MIT
