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
        # options.add_argument('--headless')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--start-maximized')
        
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

            # Calculate time span between first and last submission
            if len(parsed_times) >= 2:
                first_sub = min(parsed_times)
                last_sub = max(parsed_times)
                time_span_hours = (last_sub - first_sub).total_seconds() / 3600
            else:
                time_span_hours = 0.0

        except Exception as e:
            print(f"  Error fetching history for {student_name}: {e}")

        span_str = self._format_time(time_span_hours) if time_span_hours > 0 else "—"
        self.submissions.append({
            'name': student_name,
            'attempts': attempts,
            'timestamps': timestamps,
            'time_span_hours': time_span_hours,
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

        # Per-student breakdown
        print("\n" + "="*70)
        print(f"RESULTS: {self.assignment_name}")
        print("="*70)
        print(f"  {'Name':<40} {'Attempts':>8}  {'Time Span':>12}")
        print(f"  {'-'*40}  {'-'*8}  {'-'*12}")
        for s in self.submissions:
            span_str = self._format_time(s['time_span_hours']) if s['time_span_hours'] > 0 else "—"
            print(f"  {s['name']:<40} {s['attempts']:>8}  {span_str:>12}")

        # Extract metrics (exclude students with 0 attempts from stats)
        active = [s for s in self.submissions if s['attempts'] > 0]
        attempt_counts = [s['attempts'] for s in active]
        time_spans = [s['time_span_hours'] for s in active if s['time_span_hours'] > 0]

        print("\n" + "="*70)
        print(f"SUBMISSION STATISTICS — {self.assignment_name}")
        print("="*70)
        print(f"\nTotal Students: {len(self.submissions)}")
        print(f"Students with submissions: {len(active)}")
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
            print(f"Average:       {self._format_time(statistics.mean(time_spans))}")
            print(f"Median:        {self._format_time(statistics.median(time_spans))}")
            print(f"Min:           {self._format_time(min(time_spans))}")
            print(f"Max:           {self._format_time(max(time_spans))}")
            if len(time_spans) > 1:
                print(f"Std Deviation: {self._format_time(statistics.stdev(time_spans))}")

        print("\n" + "="*70 + "\n")

        self._plot_distributions(attempt_counts, time_spans)

    def _plot_distributions(self, attempt_counts, time_spans):
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
            ax.hist(time_spans, bins=20, color='mediumseagreen', edgecolor='white')
            ax.set_title("Time Span: First to Last Submission")
            ax.set_xlabel("Hours")
            ax.set_ylabel("Number of Students")
            ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
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
                'name':            row['student_name'],
                'attempts':        row['attempts'],
                'time_span_hours': row['time_span_hours'] or 0.0,
                'timestamps':      [],
                'submission_id':   None,
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
                'assignment_id':   self.assignment_id,
                'student_name':    s['name'],
                'assignment_name': self.assignment_name,
                'attempts':        s['attempts'],
                'time_span_hours': s['time_span_hours'] if s['time_span_hours'] > 0 else None,
            }
            for s in self.submissions
        ]

        print(f"\nSaving {len(rows)} rows to Supabase...")
        result = client.table('submission_stats').upsert(
            rows,
            on_conflict='assignment_id,student_name'
        ).execute()
        print(f"Saved successfully.")

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
    mode = input("Enter 1 or 2: ").strip()

    if mode == '2' and has_supabase:
        # --- Database mode: show each assignment from DB ---
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
