"""
Gradescope Statistics Analyzer (Selenium version)
Uses browser automation to scrape submission statistics from Gradescope.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime
import statistics
import time
import json
import csv
from tabulate import tabulate
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import sys
import os
try:
    from supabase import create_client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


class Tee:
    """Mirrors all writes to both the terminal and a file."""
    def __init__(self, filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self._file = open(filepath, 'w', encoding='utf-8')
        self._stdout = sys.stdout

    def write(self, data):
        self._stdout.write(data)
        self._file.write(data)

    def flush(self):
        self._stdout.flush()
        self._file.flush()

    def close(self):
        sys.stdout = self._stdout
        self._file.close()

    def __enter__(self):
        sys.stdout = self
        return self

    def __exit__(self, *args):
        self.close()


class GradescopeSeleniumStats:
    def __init__(self, course_id, assignment_id, assignment_name=None, test_limit=None, skip_browser=False):
        """
        Initialize the Selenium-based scraper.
        
        Args:
            course_id: Gradescope course ID
            assignment_id: Gradescope assignment ID
            assignment_name: Human-readable assignment name (optional)
            test_limit: If set, only process this many students (useful for testing)
            skip_browser: If True, skip Chrome setup (used when loading from database)
        """
        self.course_id = course_id
        self.assignment_id = assignment_id
        self.assignment_name = assignment_name or f"Assignment {assignment_id}"
        self.test_limit = test_limit
        self.submissions = []
        self.driver = None

        if skip_browser:
            return

        # Setup Chrome driver
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--start-maximized')
        options.add_argument('--window-size=1920,1080')
        
        print("Initializing browser...")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        self.wait = WebDriverWait(self.driver, 10)
    
    def set_assignment(self, assignment_id, assignment_name=None):
        """Switch to a different assignment without restarting the browser."""
        self.assignment_id = assignment_id
        self.assignment_name = assignment_name or f"Assignment {assignment_id}"
        self.submissions = []

    def login_with_cookies(self, cookies):
        """Login to Gradescope using saved cookies."""
        print("Loading Gradescope...")
        self.driver.get("https://www.gradescope.com")
        
        # Add cookies
        for cookie_name, cookie_value in cookies.items():
            self.driver.add_cookie({
                'name': cookie_name,
                'value': cookie_value,
                'domain': '.gradescope.com'
            })
        
        print("Cookies loaded, navigating to assignment...")
    
    def fetch_submissions(self):
        """Navigate to the assignment and fetch submission data."""
        url = f"https://www.gradescope.com/courses/{self.course_id}/assignments/{self.assignment_id}/review_grades"
        self.driver.get(url)
        
        time.sleep(2)  # Wait for page to load
        
        # Check if we're logged in
        if "login" in self.driver.current_url.lower() or "sign_in" in self.driver.current_url.lower():
            raise Exception(
                "Authentication failed - redirected to login page. "
                "Your signed_token may be expired. Get a fresh one from your browser."
            )
        
        if self.test_limit:
            print(f"TEST MODE: Will process only the first {self.test_limit} student(s).")
        print("Fetching submission data...")
        
        # Try to find the submissions table
        try:
            # Wait for the table to load
            table = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.table"))
            )
            
            # Extract rows
            rows = table.find_elements(By.TAG_NAME, "tr")
            data_rows = [r for r in rows[1:] if r.find_elements(By.TAG_NAME, "td")]
            print(f"Found {len(data_rows)} student rows in submission table")
            
            if self.test_limit:
                data_rows = data_rows[:self.test_limit]
                print(f"Limiting to first {len(data_rows)} row(s) for testing.\n")
            
            # Parse each row
            for i, row in enumerate(data_rows):
                cols = row.find_elements(By.TAG_NAME, "td")
                if not cols:
                    continue

                student_name = cols[0].text.strip() or f"Student {i+1}"
                print(f"[{i+1}/{len(data_rows)}] Processing: {student_name}")
                
                # Look for a submissions link in this row
                links = row.find_elements(By.CSS_SELECTOR, "a[href*='submissions']")
                if not links:
                    print(f"  No submission found for {student_name}, skipping.")
                    self.submissions.append({
                        'name': student_name,
                        'attempts': 0,
                        'timestamps': []
                    })
                    continue

                submission_id = links[0].get_attribute("href").split("/")[-1]
                self.fetch_student_submissions(student_name, submission_id)
            
        except Exception as e:
            print(f"Error parsing submission table: {e}")
            print("Trying alternative data extraction method...")
            self.extract_from_json()
    
    def extract_from_json(self):
        """Try to extract submission data from embedded JSON in the page."""
        # Look for JSON data embedded in script tags
        scripts = self.driver.find_elements(By.TAG_NAME, "script")
        
        for script in scripts:
            script_content = script.get_attribute("innerHTML")
            if "submissions" in script_content.lower():
                # Try to extract and parse JSON
                # This is a template - actual implementation depends on Gradescope's structure
                print("Found potential JSON data in page")
                # TODO: Parse JSON data
    
    def fetch_student_submissions(self, student_name, submission_id):
        """Fetch submission history for a specific student by clicking the Submission History button."""
        original_window = self.driver.current_window_handle
        
        # Open new tab so we don't lose the main table page
        self.driver.execute_script("window.open('');")
        self.driver.switch_to.window(self.driver.window_handles[-1])
        
        url = f"https://www.gradescope.com/courses/{self.course_id}/assignments/{self.assignment_id}/submissions/{submission_id}"
        self.driver.get(url)
        time.sleep(1.5)
        
        attempts = 1
        timestamps = []
        time_span_hours = 0.0
        
        try:
            # Find the Submission History button specifically (has fa-clock-o icon inside)
            # Use find_elements (no wait) so we don't hang 10s if the button doesn't exist
            history_btns = self.driver.find_elements(By.XPATH,
                "//button[contains(@class,'actionBar--action') and .//span[text()='Submission History']]"
            )
            if not history_btns:
                print(f"  No Submission History button found for {student_name} (no submission?).")
                self.submissions.append({
                    'name': student_name,
                    'attempts': 0,
                    'timestamps': [],
                    'time_span_hours': 0.0,
                    'first_submission_at': None,
                    'last_submission_at': None,
                    'submission_id': submission_id,
                })
                self.driver.close()
                self.driver.switch_to.window(original_window)
                return

            history_btn = history_btns[0]
            history_btn.click()
            print(f"  Clicked Submission History button")
            time.sleep(1)  # Wait for the history panel/modal to open
            
            # --- Read the submission history modal ---
            # Structure: tbody.table-submissionHistory--body > tr.table-submissionHistory--row
            tbody = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tbody.table-submissionHistory--body"))
            )
            rows = tbody.find_elements(By.CSS_SELECTOR, "tr.table-submissionHistory--row")
            attempts = len(rows)

            # Grab timestamps from <time datetime="..."> elements in each row
            parsed_times = []
            for row in rows:
                time_el = row.find_elements(By.TAG_NAME, "time")
                if time_el:
                    dt_str = time_el[0].get_attribute("datetime") or time_el[0].text
                    if dt_str:
                        timestamps.append(dt_str)
                        try:
                            # datetime attribute is typically ISO 8601
                            parsed_times.append(datetime.fromisoformat(dt_str.replace("Z", "+00:00")))
                        except ValueError:
                            pass
                else:
                    # Fallback: read text from the 2nd column (Submitted On)
                    cols = row.find_elements(By.TAG_NAME, "td")
                    if len(cols) > 1:
                        timestamps.append(cols[1].text.strip())

            # Calculate time span and store first/last timestamps
            if parsed_times:
                first_sub = min(parsed_times)
                last_sub = max(parsed_times)
                first_submission_at = first_sub.isoformat()
                last_submission_at = last_sub.isoformat()
                if len(parsed_times) >= 2:
                    time_span_hours = (last_sub - first_sub).total_seconds() / 3600
                else:
                    time_span_hours = 0.0
            else:
                first_submission_at = None
                last_submission_at = None
                time_span_hours = 0.0

        except Exception as e:
            print(f"  Error fetching history for {student_name}: {e}")
            first_submission_at = None
            last_submission_at = None

        span_str = self._format_time(time_span_hours) if (time_span_hours or 0) > 0 else "—"
        self.submissions.append({
            'name': student_name,
            'attempts': attempts,
            'timestamps': timestamps,
            'time_span_hours': time_span_hours,
            'first_submission_at': first_submission_at,
            'last_submission_at': last_submission_at,
            'submission_id': submission_id,
        })
        print(f"  -> {attempts} attempt(s), span: {span_str}")
        
        # Close tab and return to the main table
        self.driver.close()
        self.driver.switch_to.window(original_window)
    
    def _format_time(self, hours):
        """Format hours into a readable string."""
        return f"{round(hours, 2)} hrs"

    def calculate_statistics(self):
        """Calculate and display statistics."""
        if not self.submissions:
            print("No submission data collected.")
            return

        # Only count students with at least one submission in stats
        active = [s for s in self.submissions if s.get('attempts', 0) > 0]
        attempt_counts = [s['attempts'] for s in active]
        raw_time_spans = [
            s.get('time_span_hours') or 0.0
            for s in active
            if (s.get('time_span_hours') or 0.0) > 0
        ]

        # For time-span statistics, drop extreme outliers (>200 hrs)
        max_hours = 200
        time_spans = [h for h in raw_time_spans if h <= max_hours]
        excluded_time_spans = len(raw_time_spans) - len(time_spans)

        print("\n" + "="*70)
        print(f"SUBMISSION STATISTICS — {self.assignment_name}")
        print("="*70)
        print(f"\nTotal Students (with ≥1 submission): {len(active)}")
        if len(self.submissions) > len(active):
            print(f"Students with no submissions (excluded): {len(self.submissions) - len(active)}")
        print(f"Students with multiple attempts: {sum(1 for a in attempt_counts if a > 1)}")

        if attempt_counts:
            print("\n" + "-"*70)
            print("SUBMISSION ATTEMPTS STATISTICS")
            print("-"*70)
            print(f"Average Attempts: {statistics.mean(attempt_counts):.2f}")
            print(f"Median Attempts:  {statistics.median(attempt_counts):.0f}")
            print(f"Min Attempts:     {min(attempt_counts)}")
            print(f"Max Attempts:     {max(attempt_counts)}")
            if len(attempt_counts) > 1:
                print(f"Std Deviation:    {statistics.stdev(attempt_counts):.2f}")

        if time_spans:
            print("\n" + "-"*70)
            print("TIME BETWEEN FIRST AND LAST SUBMISSION")
            print("-"*70)
            if excluded_time_spans > 0:
                print(f"(Excluded {excluded_time_spans} student(s) with span > {max_hours} hrs)")
            print(f"Average:       {self._format_time(statistics.mean(time_spans))}")
            print(f"Median:        {self._format_time(statistics.median(time_spans))}")
            print(f"Min:           {self._format_time(min(time_spans))}")
            print(f"Max:           {self._format_time(max(time_spans))}")
            if len(time_spans) > 1:
                print(f"Std Deviation: {self._format_time(statistics.stdev(time_spans))}")

        print("\n" + "="*70 + "\n")

        self._plot_distributions(attempt_counts, time_spans, excluded_time_spans)

    def _plot_distributions(self, attempt_counts, time_spans, time_spans_excluded=0):
        """Show matplotlib distribution graphs for attempts and time spans."""
        has_attempts = len(attempt_counts) > 0
        has_times = len(time_spans) > 0

        if not has_attempts and not has_times:
            return

        num_plots = sum([has_attempts, has_times])
        fig, axes = plt.subplots(1, num_plots, figsize=(7 * num_plots, 5))
        if num_plots == 1:
            axes = [axes]

        fig.suptitle(self.assignment_name, fontsize=14, fontweight='bold')

        plot_idx = 0

        if has_attempts:
            ax = axes[plot_idx]
            bins = range(min(attempt_counts), max(attempt_counts) + 2)
            ax.hist(attempt_counts, bins=bins, align='left', color='steelblue', edgecolor='white', rwidth=0.8)
            ax.set_title("Submission Attempts Distribution")
            ax.set_xlabel("Number of Attempts")
            ax.set_ylabel("Number of Students")
            ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
            ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
            mean_val = statistics.mean(attempt_counts)
            ax.axvline(mean_val, color='tomato', linestyle='--', linewidth=1.5, label=f'Mean: {mean_val:.1f}')
            ax.legend()
            plot_idx += 1

        if has_times:
            ax = axes[plot_idx]
            max_hours = 200
            # Force bins over 0–200 so x-axis is always 0–200
            bins = 20
            ax.hist(time_spans, bins=bins, range=(0, max_hours), color='mediumseagreen', edgecolor='white')
            title = "Time Span from First to Last Submission"
            if time_spans_excluded:
                title += f"\n({time_spans_excluded} student(s) excluded >{max_hours} hrs)"
            ax.set_title(title)
            ax.set_xlabel("Hours")
            ax.set_ylabel("Number of Students")
            ax.set_xlim(0, max_hours)
            ax.set_ylim(bottom=0)
            ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
            if time_spans:
                mean_val = statistics.mean(time_spans)
                ax.axvline(mean_val, color='tomato', linestyle='--', linewidth=1.5, label=f'Mean: {mean_val:.1f} hrs')
                ax.legend()

        plt.tight_layout()
        import os
        os.makedirs("stat_distribution_graphs", exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.assignment_name).strip()
        filename = os.path.join("stat_distribution_graphs", f"{safe_name}_distributions.png")
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"Graph saved to: {filename}")
    
    def save_roster_to_supabase(self, supabase_url, supabase_key):
        """Scrape course roster SIDs from memberships page and upsert to Supabase."""
        if not SUPABASE_AVAILABLE:
            print("supabase package not installed. Run: pip install supabase")
            return
        
        client = create_client(supabase_url, supabase_key)
        
        url = f"https://www.gradescope.com/courses/{self.course_id}/memberships"
        print(f"\nLoading roster page: {url}")
        self.driver.get(url)
        time.sleep(2)
        
        rows = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr.rosterRow")
        if not rows:
            print("No roster rows found on memberships page.")
            return
        
        roster_rows = []
        for row in rows:
            try:
                # Edit button cell contains JSON with sid and full_name
                edit_btn = row.find_element(By.CSS_SELECTOR, "td.js-editButtonCell button")
                cm_json = edit_btn.get_attribute("data-cm")
                info = json.loads(cm_json) if cm_json else {}
                
                sid = info.get("sid")
                full_name = info.get("full_name") or (
                    f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
                )
                
                # Email is available as data-email on the button, or first column text
                email = edit_btn.get_attribute("data-email")
                if not email:
                    tds = row.find_elements(By.CSS_SELECTOR, "td")
                    email = tds[0].text.strip() if tds else None
                
                if not sid and not email:
                    continue
                
                roster_rows.append({
                    "course_id": self.course_id,
                    "student_email": email,
                    "student_name": full_name,
                    "sid": sid,
                })
            except Exception as e:
                print(f"  Error parsing roster row: {e}")
                continue
        
        if not roster_rows:
            print("No roster data extracted; nothing to save.")
            return
        
        print(f"Saving {len(roster_rows)} roster rows to Supabase...")
        client.table("course_roster").upsert(
            roster_rows,
            on_conflict="course_id,student_email"
        ).execute()
        print("Roster saved successfully.")
    
    def load_from_supabase(self, supabase_url, supabase_key):
        """Load submission data from Supabase for this assignment."""
        if not SUPABASE_AVAILABLE:
            print("supabase package not installed. Run: pip install supabase")
            return False

        client = create_client(supabase_url, supabase_key)
        result = (
            client.table('submission_stats')
            .select('*')
            .eq('assignment_id', self.assignment_id)
            .execute()
        )

        if not result.data:
            print(f"No data found in database for assignment '{self.assignment_id}'.")
            return False

        self.submissions = [
            {
                'name':                row['student_name'],
                'attempts':            row.get('attempts') or 0,
                'time_span_hours':     row.get('time_span_hours') or 0.0,
                'first_submission_at': row.get('first_submission_at'),
                'last_submission_at':  row.get('last_submission_at'),
                'timestamps':          [],
                'submission_id':       None,
            }
            for row in result.data
        ]
        # Use assignment name from DB if not set locally
        if result.data and result.data[0].get('assignment_name'):
            self.assignment_name = result.data[0]['assignment_name']

        print(f"Loaded {len(self.submissions)} students from database.")
        return True

    def save_to_supabase(self, supabase_url, supabase_key):
        """Upsert submission data to Supabase. Updates existing rows, inserts new ones."""
        if not SUPABASE_AVAILABLE:
            print("supabase package not installed. Run: pip install supabase")
            return
        if not self.submissions:
            print("No data to save.")
            return

        client = create_client(supabase_url, supabase_key)

        rows = [
            {
                'assignment_id':       self.assignment_id,
                'student_name':        s.get('name'),
                'assignment_name':     self.assignment_name,
                'attempts':            s.get('attempts', 0),
                'time_span_hours':     s.get('time_span_hours') or None,
                'first_submission_at': s.get('first_submission_at'),
                'last_submission_at':  s.get('last_submission_at'),
            }
            for s in self.submissions
        ]

        print(f"\nSaving {len(rows)} rows to Supabase...")
        result = client.table('submission_stats').upsert(
            rows,
            on_conflict='assignment_id,student_name'
        ).execute()
        print(f"Saved successfully.")

    def save_to_csv(self, roster_map=None):
        """Save per-student data to a CSV file in the stats/ folder.

        Args:
            roster_map: Optional dict mapping student_name -> sid (from Supabase).
        """
        if not self.submissions:
            print("No data to export.")
            return

        os.makedirs("stats", exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.assignment_name).strip()
        filepath = os.path.join("stats", f"{safe_name}_students.csv")

        headers = ["Name", "SID", "Attempts", "Time Span (hrs)", "First Submission", "Last Submission"]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()

            for s in self.submissions:
                sid = roster_map.get(s.get("name")) if roster_map else None
                span = s.get("time_span_hours") or 0.0
                writer.writerow({
                    "Name": s.get("name"),
                    "SID": sid,
                    "Attempts": s.get("attempts", 0),
                    "Time Span (hrs)": round(span, 2) if span > 0 else "",
                    "First Submission": s.get("first_submission_at") or "",
                    "Last Submission": s.get("last_submission_at") or "",
                })

        print(f"CSV file saved to: {filepath}")

    def save_suspicious_students(self, roster_map=None, max_attempts=2, max_span_hours=1.0):
        """Save students with low attempts and short time spans to a text file.

        A student is flagged if they have:
          - attempts > 0 AND attempts < max_attempts, AND
          - time_span_hours < max_span_hours.
        """
        if not self.submissions:
            print("No data to analyze for suspicious students.")
            return None

        suspects = []
        for s in self.submissions:
            attempts = s.get("attempts", 0) or 0
            span = s.get("time_span_hours")
            span = span if span is not None else 0.0

            if attempts > 0 and attempts < max_attempts and span < max_span_hours:
                suspects.append((s, attempts, span))

        if not suspects:
            print(f"No students met the criteria (attempts < {max_attempts}, span < {max_span_hours} hrs).")
            return None

        os.makedirs("stats", exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.assignment_name).strip()
        filepath = os.path.join("stats", f"{safe_name}_sus_students.txt")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Suspicious students for {self.assignment_name}\n")
            f.write(f"Criteria: attempts < {max_attempts}, span (hrs) < {max_span_hours}\n\n")
            f.write("Name\tSID\tAttempts\tSpan (hrs)\n")

            for s, attempts, span in suspects:
                name = s.get("name") or ""
                sid = ""
                if roster_map:
                    sid_val = roster_map.get(name)
                    sid = str(sid_val) if sid_val is not None else ""
                f.write(f"{name}\t{sid}\t{attempts}\t{span:.2f}\n")

        print(f"Suspicious students file saved to: {filepath}")
        return filepath

    def cleanup(self):
        """Close the browser."""
        self.driver.quit()


def load_config():
    """Load configuration from config.json."""
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_config(config):
    """Save configuration to config.json."""
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)


def setup_config():
    """Interactive setup for configuration."""
    print("\n" + "="*70)
    print("GRADESCOPE STATISTICS ANALYZER (SELENIUM) - SETUP")
    print("="*70 + "\n")
    
    config = {}
    
    print("To find your course and assignment IDs:")
    print("1. Go to your Gradescope assignment page")
    print("2. Look at the URL: https://www.gradescope.com/courses/COURSE_ID/assignments/ASSIGNMENT_ID")
    print()
    
    config['course_id'] = input("Enter Course ID: ").strip()

    config['assignments'] = []
    print("\nEnter assignments to analyze (leave Assignment ID blank to finish):")
    while True:
        assignment_id = input("  Assignment ID: ").strip()
        if not assignment_id:
            break
        assignment_name = input("  Assignment Name (e.g. HW3, Lab 5): ").strip()
        config['assignments'].append({'assignment_id': assignment_id, 'assignment_name': assignment_name})
        print(f"  Added. ({len(config['assignments'])} total) Enter another or leave blank to finish.\n")

    if not config['assignments']:
        print("No assignments added. Exiting.")
        return config
    
    print("\nTo get your authentication cookies:")
    print("1. Log in to Gradescope in your browser")
    print("2. Open Developer Tools (F12)")
    print("3. Go to Application/Storage > Cookies > https://www.gradescope.com")
    print("4. Find and copy the 'signed_token' cookie value")
    print()
    
    config['cookies'] = {
        'signed_token': input("Enter signed_token cookie: ").strip()
    }
    
    remember_me = input("Enter remember_me cookie (optional, press Enter to skip): ").strip()
    if remember_me:
        config['cookies']['remember_me'] = remember_me
    
    save_config(config)
    print("\nConfiguration saved to config.json")
    return config


def _stats_filepath(assignment_name):
    """Return the path to save stats text for a given assignment."""
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in assignment_name).strip()
    return os.path.join("stats", f"{safe_name}_stats.txt")


def _load_roster_map(course_id, supabase_url, supabase_key):
    """Load {student_name -> sid} mapping from Supabase course_roster."""
    if not SUPABASE_AVAILABLE or not (supabase_url and supabase_key):
        return {}
    try:
        client = create_client(supabase_url, supabase_key)
        result = (
            client.table("course_roster")
            .select("student_name,sid")
            .eq("course_id", course_id)
            .execute()
        )
        data = result.data or []
        return {
            row["student_name"]: row.get("sid")
            for row in data
            if row.get("student_name")
        }
    except Exception as e:
        print(f"Warning: could not load roster SIDs from Supabase: {e}")
        return {}


def get_assignments(config):
    """Return assignments list, supporting both old single and new multi-assignment format."""
    if 'assignments' in config:
        return config['assignments']
    # Backward compat: single assignment at top level
    if 'assignment_id' in config:
        return [{'assignment_id': config['assignment_id'], 'assignment_name': config.get('assignment_name', '')}]
    return []


def main():
    """Main entry point."""
    print("\nGradescope Statistics Analyzer (Selenium Version)")
    print("="*70)

    config = load_config()
    if not config:
        print("\nNo configuration found. Let's set it up!")
        config = setup_config()
    else:
        assignments = get_assignments(config)
        labels = ", ".join(a.get('assignment_name') or a['assignment_id'] for a in assignments)
        print(f"\nCourse {config['course_id']} — {len(assignments)} assignment(s): {labels}")
        reconfigure = input("Reconfigure? (y/n): ").strip().lower()
        if reconfigure == 'y':
            config = setup_config()

    assignments = get_assignments(config)
    if not assignments:
        print("No assignments configured. Please reconfigure.")
        return

    has_supabase = bool(config.get('supabase_url') and config.get('supabase_key'))
    print("\nWhat would you like to do?")
    print("  1. Scrape Gradescope (opens browser)")
    if has_supabase:
        print("  2. View stats from database")
        print("  3. Sync course roster SIDs only")
        print("  4. Find suspicious students (from database)")
        mode = input("Enter 1, 2, 3, or 4: ").strip()
    else:
        mode = input("Enter 1: ").strip()

    if mode == '3' and has_supabase:
        # --- Roster-only mode: just sync course roster SIDs, no assignment scraping ---
        analyzer = None
        try:
            first = assignments[0]
            analyzer = GradescopeSeleniumStats(
                config['course_id'],
                first['assignment_id'],
                assignment_name=first.get('assignment_name'),
                skip_browser=False,
            )
            analyzer.login_with_cookies(config['cookies'])
            analyzer.save_roster_to_supabase(config['supabase_url'], config['supabase_key'])
        except Exception as e:
            print(f"\nError while syncing roster: {e}")
        finally:
            if analyzer and analyzer.driver:
                print("\nClosing browser...")
                analyzer.cleanup()

    elif mode == '2' and has_supabase:
        # --- Database mode: show each assignment from DB ---
        roster_map = _load_roster_map(
            config['course_id'], config['supabase_url'], config['supabase_key']
        )
        for assignment in assignments:
            analyzer = GradescopeSeleniumStats(
                config['course_id'],
                assignment['assignment_id'],
                assignment_name=assignment.get('assignment_name'),
                skip_browser=True,
            )
            loaded = analyzer.load_from_supabase(config['supabase_url'], config['supabase_key'])
            if loaded:
                stat_file = _stats_filepath(analyzer.assignment_name)
                with Tee(stat_file):
                    analyzer.calculate_statistics()
                print(f"Stats saved to: {stat_file}")
                analyzer.save_to_csv(roster_map)

    elif mode == '4' and has_supabase:
        # --- Suspicious-students mode: flag low-attempt / short-span students from DB ---
        while True:
            max_attempts_input = input(
                "Flag students with FEWER than how many attempts? (e.g. 2): "
            ).strip()
            try:
                max_attempts = int(max_attempts_input)
                if max_attempts <= 0:
                    raise ValueError
                break
            except ValueError:
                print("Please enter a positive integer for attempts.")

        while True:
            max_span_input = input(
                "Flag students with LESS than how many hours between first and last submission? (e.g. 1.5): "
            ).strip()
            try:
                max_span_hours = float(max_span_input)
                if max_span_hours < 0:
                    raise ValueError
                break
            except ValueError:
                print("Please enter a non-negative number for hours (e.g. 0, 0.5, 2).")

        roster_map = _load_roster_map(
            config['course_id'], config['supabase_url'], config['supabase_key']
        )

        for assignment in assignments:
            analyzer = GradescopeSeleniumStats(
                config['course_id'],
                assignment['assignment_id'],
                assignment_name=assignment.get('assignment_name'),
                skip_browser=True,
            )
            loaded = analyzer.load_from_supabase(config['supabase_url'], config['supabase_key'])
            if loaded:
                path = analyzer.save_suspicious_students(
                    roster_map=roster_map,
                    max_attempts=max_attempts,
                    max_span_hours=max_span_hours,
                )
                if path:
                    print(f"Suspicious students for '{analyzer.assignment_name}' written to: {path}")

    else:
        # --- Scrape mode: one browser session, loop through assignments ---
        test_input = input("\nRun in TEST mode? Enter number of students to test (e.g. 3), or press Enter for all: ").strip()
        test_limit = None
        if test_input.isdigit() and int(test_input) > 0:
            test_limit = int(test_input)
            print(f"Test mode: will process only {test_limit} student(s) per assignment.")

        analyzer = None
        try:
            # Init browser once using the first assignment
            first = assignments[0]
            analyzer = GradescopeSeleniumStats(
                config['course_id'],
                first['assignment_id'],
                assignment_name=first.get('assignment_name'),
                test_limit=test_limit,
            )
            analyzer.login_with_cookies(config['cookies'])
            # Optionally sync roster SIDs once per run (per course)
            roster_map = {}
            if has_supabase:
                sync_roster = input("\nSync course roster SIDs to Supabase? (y/n): ").strip().lower()
                if sync_roster == 'y':
                    analyzer.save_roster_to_supabase(config['supabase_url'], config['supabase_key'])
                roster_map = _load_roster_map(
                    config['course_id'], config.get('supabase_url'), config.get('supabase_key')
                )

            for i, assignment in enumerate(assignments):
                print(f"\n{'='*70}")
                print(f"Assignment {i+1}/{len(assignments)}: {assignment.get('assignment_name') or assignment['assignment_id']}")
                print("="*70)

                analyzer.set_assignment(assignment['assignment_id'], assignment.get('assignment_name'))
                analyzer.fetch_submissions()

                stat_file = _stats_filepath(analyzer.assignment_name)
                with Tee(stat_file):
                    analyzer.calculate_statistics()
                print(f"Stats saved to: {stat_file}")
                analyzer.save_to_csv(roster_map)

                if has_supabase:
                    analyzer.save_to_supabase(config['supabase_url'], config['supabase_key'])

        except Exception as e:
            print(f"\nError: {e}")
            print("\nIf authentication failed, try reconfiguring with fresh cookies.")

        finally:
            if analyzer and analyzer.driver:
                print("\nClosing browser...")
                analyzer.cleanup()


if __name__ == "__main__":
    main()
