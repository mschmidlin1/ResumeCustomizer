# Textkernel (Tx Platform) resume scoring

The **Score** tab sends a PDF resume and a pasted job description to the [Textkernel Tx Platform](https://developer.textkernel.com/tx-platform/v10/overview/) (formerly Sovren) and displays bimetric match scores.

Do **not** commit `account_id` or `service_key`. Put them only in `.streamlit/secrets.toml` (gitignored) or GitHub Actions secrets for deploy.

## Account email (why not Gmail)

Tx Console self-serve signup **rejects free email providers** (Gmail, Yahoo, Outlook, and similar). It does not require an employer domain; it only blocklists known free hosts.

This project’s Tx account identity is **`michael@schmidlin.casa`**.

`schmidlin.casa` is on Cloudflare. Mail for that address is **forwarded** into Gmail with [Cloudflare Email Routing](https://developers.cloudflare.com/email-routing/). You still read mail in Gmail. Textkernel only sees `@schmidlin.casa`.

Signup, password resets, and billing receipts only need **inbound** mail. Paying for credits is done in the Tx Console with a card; you do not need to *send* from `michael@schmidlin.casa`.

Routing does **not** lock the domain. A real mailbox later means: create the address at the new provider, turn Routing off, point MX at that provider. Do not run Routing and a second mail server on the same domain at once. Site DNS (`customizer.schmidlin.casa`) is unrelated.

### Set up Email Routing (once)

1. Open the [Cloudflare dashboard](https://dash.cloudflare.com/) and select **schmidlin.casa**.
2. Go to **Email** → **Email Routing** and enable it. Cloudflare adds MX (and related) records. This domain had no MX before Routing.
3. Add your Gmail address as a **destination** and confirm the verification email Cloudflare sends to Gmail (check spam).
4. Create a routing rule: **`michael@schmidlin.casa`** → that Gmail address.
5. Optional check: send a test message to `michael@schmidlin.casa` and confirm it arrives in Gmail.

### Create the Tx account

1. Open [https://cloud.textkernel.com/tx/console/register](https://cloud.textkernel.com/tx/console/register).
2. Register with **`michael@schmidlin.casa`** (not Gmail).
3. Confirm the Textkernel verification email in Gmail (check spam).
4. Sign in to the [Tx Console](https://cloud.textkernel.com/tx/console).
5. Copy **Account ID**, **Service Key**, and note the **data center** (US, EU, or AU).
6. Confirm the trial credit balance (advertised as 500).

### Local secrets

Copy [`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example) to `.streamlit/secrets.toml` if you have not already. Add:

```toml
[textkernel]
account_id = "..."
service_key = "..."
```

Restart Streamlit after editing secrets. Data center and parse add-on flags are not secrets; they live in [`src/resume_scorer/settings.py`](../src/resume_scorer/settings.py).

### Production (optional)

The deploy workflow writes `[textkernel]` into the cluster `secrets.toml` when these GitHub Actions secrets are set:

- `TEXTKERNEL_ACCOUNT_ID`
- `TEXTKERNEL_SERVICE_KEY`

If they are unset, the Score tab still loads but Run will tell you Textkernel is not configured.

## How scoring works

One **Run** is three REST calls (v10). There is no Python SDK; the app uses `httpx`.

| Step | Endpoint | Typical cost |
|------|----------|----------------|
| Parse resume (PDF as base64) | `POST /v10/parser/resume` | 1 credit (+0.05 if OCR runs on a scan) |
| Parse job (pasted text as UTF-8 `.txt` base64) | `POST /v10/parser/joborder` | 1 credit |
| Score resume against job | `POST /v10/scorer/bimetric/joborder` | 1 credit for one target |

Base cost is about **3 credits per Run** (~166 Runs on a 500-credit trial). Do not call `GET /v10/account` (that costs 1 credit). Remaining credits are on every response (`Info.CustomerDetails.CreditsRemaining`). Per-call cost is `Info.TransactionCost`.

Auth headers: `Tx-AccountId`, `Tx-ServiceKey`. Base URL depends on data center:

- US: `https://api.us.textkernel.com/tx/v10`
- EU: `https://api.eu.textkernel.com/tx/v10`
- AU: `https://api.au.textkernel.com/tx/v10`

Job-as-source (`bimetric/joborder`) is the right direction for “how well does this resume fit this posting.” The other bimetric URL (`bimetric/resume`) flips source/target. Matcher/search APIs need an index and are not used here.

## Data center and parse add-on flags

Edit [`src/resume_scorer/settings.py`](../src/resume_scorer/settings.py) and restart Streamlit. `DATA_CENTER` must match the Tx Console account (`US`, `EU`, or `AU`).

New Tx accounts default to **skills taxonomy V2**. Bimetric scoring (Search & Match) refuses those parsed documents unless skills were normalized, with: `When using the V2 skills with Tx Search & Match you must also use skills normalization.` So `NORMALIZE_SKILLS` stays **on**. Turning it off saves 0.1 credits per parse but scoring will fail.

| Flag | Tx request | Extra cost | What it does |
|------|------------|------------|----------------|
| `NORMALIZE_SKILLS` | `SkillsSettings.Normalize` + taxonomy V2 | +0.1 per parse | Required for scoring on V2 accounts. Maps skill synonyms (e.g. JS vs JavaScript). |
| `NORMALIZE_JOB_TITLES` | `ProfessionsSettings.Normalize` | +0.2 per parse | Optional. Profession taxonomy on recent titles. Bimetric already does some title variation matching without this. |

Geocoding and the LLM parser are **not** wired. OCR for scanned PDFs is a Tx Console setting, not an app flag.

## Credit tracking in this app

Anthropic spend stays in Mongo database `resume_customizer` (env `RESUME_CUSTOMIZER_DB`).

Textkernel usage is a **separate database** on the same server (`MONGODB_URI`):

- Env: `RESUME_SCORER_DB` (default `resume_scorer`)
- Collection: `scorer_usage`
- One document **per Score Run** (including partial billed failures)
- Sidebar **Textkernel credits used** = sum of `credits_used` in that collection
- Caption **Last known remaining** = `credits_remaining` from the newest run that returned it

That sidebar total is **this tool’s** usage, not the whole Tx account (Swagger or the demo UI would not be included unless they share this ledger).

## UI mapping

The API does not return a `match_results` object. The app maps:

- Overall: `Value.Matches[0].SovScore` (also WeightedScore and ReverseCompatibilityScore)
- Category bars: `EnrichedScoreData.*.UnweightedScore` (job titles, skills, education, and others if present)
- Skills: `EnrichedScoreData.Skills.Found` / `NotFound`

There is no `experience_years` category score from bimetric scoring.

## Code

- `src/resume_scorer/` — client, mapping, scoring orchestration, Mongo ledger, Score tab UI
- `src/resume_lib/` — shared secrets and auth
- `src/resume_customizer/` — Customize tab (Claude)
