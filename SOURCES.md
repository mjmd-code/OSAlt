# OSAlt — Data Sources

This file documents all data sources used in OSAlt pipelines: endpoints, retrieval dates, known limitations, and coverage notes. Updated manually when pipeline runs complete.

---

## Job Postings

**Primary source:** Adzuna Jobs API  
**Endpoint:** `https://api.adzuna.com/v1/api/jobs/us/search/{page}`  
**Documentation:** https://developer.adzuna.com/docs/search  
**Authentication:** App ID + App Key (free tier, 100 requests/day)  
**Geographic scope:** United States (national, no location filter at query stage)  

### Coverage validation (spot checks, UK market used as proxy)

| Company | Ticker | Adzuna count | Official careers site | Coverage confidence | Notes |
|---------|--------|-------------|----------------------|--------------------|-|
| Palo Alto Networks | PANW | ~33 | ~35 | High | Within 6% |
| CrowdStrike | CRWD | ~67 | ~62 | High | Adzuna slightly over — likely duplicate/recruiter postings |
| Fortinet | FTNT | — | — | Medium | Not yet validated |
| Zscaler | ZS | — | — | Medium | Not yet validated |


*Note: UK spot checks used as a proxy for Adzuna's general coverage quality. US coverage may differ. Validate before drawing conclusions from any company with Medium confidence.*

### Known limitations

- **Free tier rate limit:** 100 requests/day. Pipeline caps at 90 to provide margin. Large companies may require multiple days to build a full historical dataset.
- **No historical depth:** Adzuna returns currently active postings only. No backfill of expired listings. Time-series analysis depends on repeated pipeline runs over time.
- **Company name matching:** Adzuna's `company` field is populated by the poster (employer or recruiter) and is inconsistent. Pipeline uses a two-stage match: query → alias filter. False negatives possible where recruiters post without naming the employer.
- **Description truncation:** Adzuna descriptions are sometimes truncated. Full descriptions require fetching the redirect URL — not implemented in v1.

### Retrieval log

| Run date | Companies | Records fetched | Notes |
|----------|-----------|----------------|-------|
| — | — | — | Not yet run |
