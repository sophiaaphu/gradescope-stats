# Gradescope Statistics Analyzer

A tool to analyze Gradescope autograder assignment statistics **without downloading all submissions**. Uses browser automation to log in and collect submission attempt data for each student.

## Features

- **Browser-Based Auth**: Uses Selenium with your session cookies — no password needed
- **Per-Student Breakdown**: Name, attempt count, and time span (first to last submission) for every student
- **Distribution Graphs**: Matplotlib histograms for attempts and time spans, saved as PNG files
- **Supabase Integration**: Results are automatically saved to a database after every scrape — reload and view stats anytime without re-running the browser
- **Test Mode**: Process just a few students first to verify everything is working
- **Two Modes**: Scrape fresh data, or view stats from a previously saved database run

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
pip install matplotlib supabase
```

### 2. Set Up Supabase

Create a free project at [supabase.com](https://supabase.com), then run this in the SQL editor:

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

### 3. Set Up Config

```bash
cp config.example.json config.json
```

Fill in `config.json`:

```json
{
    "course_id": "123456",
    "assignment_id": "789012",
    "assignment_name": "HW3 - Sorting Algorithms",
    "cookies": {
        "signed_token": "your_signed_token_here",
        "_gradescope_session": "your_session_cookie_here"
    },
    "supabase_url": "https://your-project.supabase.co",
    "supabase_key": "your_anon_key_here"
}
```

See [QUICKSTART.md](QUICKSTART.md) for how to get your cookies and Supabase credentials.

### 3. Run the Script

```bash
python gradescope_stats_selenium.py
```

You'll be asked to choose a mode:

```
What would you like to do?
  1. Scrape Gradescope (opens browser)
  2. View stats from database
Enter 1 or 2:
```

## What You'll See

### Per-Student Breakdown
```
======================================================================
RESULTS: HW3 - Sorting Algorithms
======================================================================
  Name                                     Attempts     Time Span
  ----------------------------------------  --------  ------------
  Alice Smith                                      5       3.25 hrs
  Bob Jones                                        2      18.50 hrs
  Carol White                                      1             —
```

### Aggregate Statistics
```
======================================================================
SUBMISSION STATISTICS — HW3 - Sorting Algorithms
======================================================================

Total Students: 150
Students with submissions: 148
Students with multiple attempts: 112

----------------------------------------------------------------------
SUBMISSION ATTEMPTS STATISTICS
----------------------------------------------------------------------
Average Attempts: 3.45
Median Attempts:  3
Min Attempts:     1
Max Attempts:     15
Std Deviation:    2.34

----------------------------------------------------------------------
TIME BETWEEN FIRST AND LAST SUBMISSION
----------------------------------------------------------------------
Average:       12.5 hrs
Median:        8.3 hrs
Min:           0.08 hrs
Max:           96.2 hrs
```

### Distribution Graphs

Two histograms are saved to `stat_distribution_graphs/` as a PNG:
- Attempt count distribution
- Time span distribution (hours)

## Configuration

| Field | Required | Description |
|---|---|---|
| `course_id` | Yes | From the Gradescope URL |
| `assignment_id` | Yes | From the Gradescope URL |
| `assignment_name` | Yes | Human-readable label (used in output and filenames) |
| `cookies` | Yes | `_gradescope_session` and `signed_token` from your browser |
| `supabase_url` | Yes | Your Supabase project URL |
| `supabase_key` | Yes | Your Supabase anon key |

Results are automatically saved to Supabase after every scrape. Running the scraper again for the same assignment will **update** existing rows rather than duplicating them, thanks to the `(assignment_id, student_name)` primary key.

## Troubleshooting

### Authentication Errors
- Your cookies have expired — get fresh ones from your browser (see QUICKSTART.md)
- Make sure you copy both `_gradescope_session` **and** `signed_token`

### No Data Returned
- Verify the course and assignment IDs are correct
- Make sure you have instructor/TA access to the assignment

### Attempt Count Looks Wrong
- Run with test mode set to `1` and watch the Chrome window to confirm the Submission History modal is opening correctly

## Privacy & Security

- `config.json` and `stat_distribution_graphs/` are excluded from git via `.gitignore`
- Never share your cookies — they give full access to your Gradescope account

## License

Free to use for educational purposes.
