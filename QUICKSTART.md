# Quick Start Guide

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
pip install matplotlib supabase
```

## Step 2: Get Your Credentials

### A. Find Course and Assignment IDs

1. Go to your Gradescope assignment
2. Look at the URL:
   ```
   https://www.gradescope.com/courses/XXXXX/assignments/YYYYY
   ```
3. `XXXXX` = Course ID, `YYYYY` = Assignment ID

### B. Get Authentication Cookies

You need two cookies from your browser. You must be logged in to Gradescope first.

1. Press **F12** → **Application** tab (Chrome) or **Storage** tab (Firefox)
2. Go to **Cookies** → **https://www.gradescope.com**
3. Copy the values for **both**:
   - `_gradescope_session` — main session cookie (**required**, expires when browser closes)
   - `signed_token` — remember-me token

> **Note:** If you get an auth error, come back here and copy a fresh `_gradescope_session`.

### C. Set Up Supabase

Results are automatically saved to Supabase after every scrape, so this is required.

1. Create a free project at [supabase.com](https://supabase.com)
2. Go to **Settings → API** and copy your **Project URL** and **anon public** key
3. Run this in your Supabase **SQL Editor**:

```sql
CREATE TABLE submission_stats (
    assignment_id   TEXT,
    student_name    TEXT,
    assignment_name TEXT,
    attempts        INTEGER,
    time_span_hours FLOAT,
    PRIMARY KEY (assignment_id, student_name)
);
```

### D. Fill In config.json

```json
{
    "course_id": "YOUR_COURSE_ID",
    "assignment_id": "YOUR_ASSIGNMENT_ID",
    "assignment_name": "HW3 - Sorting Algorithms",
    "cookies": {
        "_gradescope_session": "paste_here",
        "signed_token": "paste_here"
    },
    "supabase_url": "https://your-project.supabase.co",
    "supabase_key": "your_anon_key_here"
}
```

## Step 3: Run the Script

```bash
python gradescope_stats_selenium.py
```

### Choosing a Mode

```
What would you like to do?
  1. Scrape Gradescope (opens browser)
  2. View stats from database
Enter 1 or 2:
```

**Mode 1 — Scrape:** Opens Chrome, logs in with your cookies, clicks through each student's Submission History, collects data. At the end you can save to Supabase.

**Mode 2 — Database:** No browser. Fetches previously saved data from Supabase and shows stats + graphs instantly.

### Test Mode (Mode 1 only)

```
Run in TEST mode? Enter number of students to test (e.g. 3), or press Enter for all: 3
Test mode: will process only 3 student(s).
```

Enter a small number to verify everything works before running on the full class.

## Output

### Terminal
```
[1/150] Processing: Alice Smith
  Clicked Submission History button
  -> 5 attempt(s), span: 3.25 hrs
[2/150] Processing: Bob Jones
  Clicked Submission History button
  -> 2 attempt(s), span: 18.5 hrs
...

======================================================================
RESULTS: HW3 - Sorting Algorithms
======================================================================
  Name                                     Attempts     Time Span
  ----------------------------------------  --------  ------------
  Alice Smith                                      5      3.25 hrs
  Bob Jones                                        2     18.50 hrs
  ...

Saving 150 rows to Supabase...
Saved successfully.
```

### Graph

A PNG file is saved to `stat_distribution_graphs/`:
```
stat_distribution_graphs/HW3 - Sorting Algorithms_distributions.png
```

It contains two side-by-side histograms:
- **Attempts distribution** — how many students made 1, 2, 3... attempts
- **Time span distribution** — how many hours between each student's first and last submission

## Troubleshooting

### Redirected to login / Auth failed
- Copy a fresh `_gradescope_session` from your browser (Step 2B)
- This cookie expires when you close your browser

### No data in database (Mode 2)
- Run Mode 1 first — it saves to Supabase automatically
- Check that your `supabase_url` and `supabase_key` are correct in `config.json`

### Attempt count always the same for everyone
- Run Mode 1 with test limit `1` and watch the Chrome window
- Confirm the Submission History modal opens and shows different row counts

## Security

**Never commit `config.json` to git** — it contains your session cookies and Supabase key. The `.gitignore` already excludes it, along with the `stat_distribution_graphs/` folder.
