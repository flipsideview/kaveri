#!/usr/bin/env python3
"""
KAVERI Direct API Search Tool
==============================
Searches EC records directly via API without browser automation.
Uses 2Captcha/Anti-Captcha for automatic CAPTCHA solving.

Usage:
  1. Run with --login to authenticate and save session
  2. Run search with saved session

Environment Variables:
  CAPTCHA_API_KEY - Your 2Captcha or Anti-Captcha API key
  CAPTCHA_SERVICE - "2captcha" (default) or "anticaptcha"
"""

import os
import sys
import json
import time
import base64
import logging
import argparse
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
import csv

# Selenium for initial login only
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
BASE_URL = "https://kaveri.karnataka.gov.in"
API_URL = f"{BASE_URL}/api"
SESSION_FILE = Path(__file__).parent / ".kaveri_session.json"
EXPORTS_DIR = Path(__file__).parent / "exports"
LOCATIONS_DB = Path(__file__).parent / "kaveri_locations.db"

# Default headers
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


@dataclass
class CaptchaSolution:
    """CAPTCHA solution result"""
    captcha_id: str
    captcha_code: str
    cost: float = 0.0


class CaptchaSolver:
    """Handles CAPTCHA solving via 2Captcha or Anti-Captcha"""
    
    def __init__(self, api_key: str, service: str = "2captcha"):
        self.api_key = api_key
        self.service = service.lower()
        
        if self.service == "2captcha":
            self.submit_url = "http://2captcha.com/in.php"
            self.result_url = "http://2captcha.com/res.php"
        elif self.service == "anticaptcha":
            self.submit_url = "https://api.anti-captcha.com/createTask"
            self.result_url = "https://api.anti-captcha.com/getTaskResult"
        else:
            raise ValueError(f"Unknown CAPTCHA service: {service}")
    
    def solve_image(self, image_base64: str, timeout: int = 120) -> str:
        """
        Submit image CAPTCHA and wait for solution.
        Returns the solved CAPTCHA text.
        """
        if self.service == "2captcha":
            return self._solve_2captcha(image_base64, timeout)
        else:
            return self._solve_anticaptcha(image_base64, timeout)
    
    def _solve_2captcha(self, image_base64: str, timeout: int) -> str:
        """Solve using 2Captcha service"""
        # Submit CAPTCHA
        response = requests.post(self.submit_url, data={
            "key": self.api_key,
            "method": "base64",
            "body": image_base64,
            "json": 1
        })
        result = response.json()
        
        if result.get("status") != 1:
            raise Exception(f"2Captcha submit failed: {result.get('request')}")
        
        task_id = result["request"]
        logger.info(f"  CAPTCHA submitted to 2Captcha, task_id: {task_id}")
        
        # Poll for result
        start_time = time.time()
        while time.time() - start_time < timeout:
            time.sleep(5)
            
            response = requests.get(self.result_url, params={
                "key": self.api_key,
                "action": "get",
                "id": task_id,
                "json": 1
            })
            result = response.json()
            
            if result.get("status") == 1:
                solution = result["request"]
                logger.info(f"  CAPTCHA solved: {solution}")
                return solution
            elif result.get("request") != "CAPCHA_NOT_READY":
                raise Exception(f"2Captcha error: {result.get('request')}")
        
        raise Exception("CAPTCHA solving timeout")
    
    def _solve_anticaptcha(self, image_base64: str, timeout: int) -> str:
        """Solve using Anti-Captcha service"""
        # Submit task
        response = requests.post(self.submit_url, json={
            "clientKey": self.api_key,
            "task": {
                "type": "ImageToTextTask",
                "body": image_base64,
                "phrase": False,
                "case": True,
                "numeric": 0,
                "math": False,
                "minLength": 5,
                "maxLength": 6
            }
        })
        result = response.json()
        
        if result.get("errorId") != 0:
            raise Exception(f"Anti-Captcha submit failed: {result.get('errorDescription')}")
        
        task_id = result["taskId"]
        logger.info(f"  CAPTCHA submitted to Anti-Captcha, task_id: {task_id}")
        
        # Poll for result
        start_time = time.time()
        while time.time() - start_time < timeout:
            time.sleep(5)
            
            response = requests.post(self.result_url, json={
                "clientKey": self.api_key,
                "taskId": task_id
            })
            result = response.json()
            
            if result.get("status") == "ready":
                solution = result["solution"]["text"]
                logger.info(f"  CAPTCHA solved: {solution}")
                return solution
            elif result.get("errorId") != 0:
                raise Exception(f"Anti-Captcha error: {result.get('errorDescription')}")
        
        raise Exception("CAPTCHA solving timeout")


class KaveriDirectAPI:
    """Direct API client for KAVERI portal"""
    
    def __init__(self, captcha_api_key: str = None, captcha_service: str = "2captcha"):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._append_token: Optional[str] = None
        
        # Initialize CAPTCHA solver if API key provided
        self.captcha_solver = None
        if captcha_api_key:
            self.captcha_solver = CaptchaSolver(captcha_api_key, captcha_service)
            logger.info(f"CAPTCHA solver initialized ({captcha_service})")
        
        # Load saved session if exists
        self._load_session()
    
    def _load_session(self):
        """Load saved session from file"""
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE, "r") as f:
                    data = json.load(f)
                self._append_token = data.get("append_token")
                
                # Load cookies
                for cookie in data.get("cookies", []):
                    self.session.cookies.set(
                        cookie["name"],
                        cookie["value"],
                        domain=cookie.get("domain", "kaveri.karnataka.gov.in")
                    )
                
                if self._append_token:
                    logger.info(f"Loaded saved session (token: {self._append_token[:16]}...)")
            except Exception as e:
                logger.warning(f"Failed to load session: {e}")
    
    def _save_session(self):
        """Save session to file"""
        data = {
            "append_token": self._append_token,
            "cookies": [
                {"name": c.name, "value": c.value, "domain": c.domain}
                for c in self.session.cookies
            ],
            "saved_at": datetime.now().isoformat()
        }
        with open(SESSION_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Session saved to {SESSION_FILE}")
    
    def login_via_browser(self) -> bool:
        """
        Open browser for manual login, then extract session token.
        User needs to complete login (username, password, CAPTCHA, OTP).
        """
        if not SELENIUM_AVAILABLE:
            logger.error("Selenium not installed. Run: pip install selenium webdriver-manager")
            return False
        
        print("\n" + "=" * 60)
        print("KAVERI LOGIN - Browser will open")
        print("=" * 60)
        print("Please complete these steps:")
        print("  1. Enter username and password")
        print("  2. Solve CAPTCHA")
        print("  3. Enter OTP")
        print("  4. Navigate to 'Search by Party Name' page")
        print("  5. Press ENTER in this terminal when ready")
        print("=" * 60 + "\n")
        
        # Setup Chrome
        opts = Options()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        
        try:
            driver.get(f"{BASE_URL}/ec-search-citizen")
            
            # Wait for user to complete login
            input("\nPress ENTER after you've logged in and reached the search page...")
            
            # Extract _append token from localStorage or network
            # The token is typically stored in localStorage
            try:
                # Try to get from localStorage
                local_storage = driver.execute_script("return window.localStorage;")
                session_storage = driver.execute_script("return window.sessionStorage;")
                
                # Look for token in storage
                for key in local_storage:
                    if "token" in key.lower() or "auth" in key.lower():
                        logger.info(f"Found localStorage key: {key}")
                
                # Get cookies
                cookies = driver.get_cookies()
                for cookie in cookies:
                    self.session.cookies.set(cookie["name"], cookie["value"])
                    logger.info(f"Extracted cookie: {cookie['name']}")
                
                # The _append token might need to be intercepted from network requests
                # Let's try to make a test API call to see if session works
                
                # For now, let's prompt user to provide the token manually
                print("\n" + "-" * 60)
                print("To get the _append token:")
                print("  1. Open Chrome DevTools (F12)")
                print("  2. Go to Network tab")
                print("  3. Make any dropdown selection on the search page")
                print("  4. Look at request headers for '_append' value")
                print("-" * 60)
                
                token = input("\nPaste the _append token value: ").strip()
                
                if token:
                    self._append_token = token
                    self._save_session()
                    logger.info("Session extracted successfully!")
                    return True
                else:
                    logger.warning("No token provided")
                    return False
                    
            except Exception as e:
                logger.error(f"Failed to extract session: {e}")
                return False
                
        finally:
            driver.quit()
    
    def generate_captcha(self) -> tuple[str, bytes]:
        """
        Generate a new CAPTCHA.
        Returns (captcha_id, image_bytes)
        """
        url = f"{API_URL}/Generate"
        response = self.session.get(url)
        response.raise_for_status()
        
        captcha_id = response.headers.get("i")
        image_bytes = response.content
        
        logger.debug(f"Generated CAPTCHA: {captcha_id}")
        return captcha_id, image_bytes
    
    def solve_captcha(self, image_bytes: bytes) -> str:
        """
        Solve CAPTCHA using configured service or manual input.
        Returns the solution text.
        """
        if self.captcha_solver:
            # Use automatic solving
            image_base64 = base64.b64encode(image_bytes).decode()
            return self.captcha_solver.solve_image(image_base64)
        else:
            # Manual solving - save image and prompt user
            captcha_path = Path(__file__).parent / "captcha_temp.png"
            with open(captcha_path, "wb") as f:
                f.write(image_bytes)
            
            print(f"\nCAPTCHA saved to: {captcha_path}")
            print("Open the image and enter the text:")
            solution = input("CAPTCHA code: ").strip()
            
            # Clean up
            captcha_path.unlink(missing_ok=True)
            
            return solution
    
    def search_ec(
        self,
        village_code: str,
        party_name: str,
        from_date: str,
        to_date: str,
        middle_name: str = "",
        last_name: str = ""
    ) -> List[Dict]:
        """
        Perform EC search via direct API call.
        Returns list of results.
        """
        if not self._append_token:
            raise Exception("No session token. Please login first.")
        
        # Generate and solve CAPTCHA
        logger.info(f"  Generating CAPTCHA for village {village_code}...")
        captcha_id, captcha_image = self.generate_captcha()
        
        logger.info(f"  Solving CAPTCHA...")
        captcha_code = self.solve_captcha(captcha_image)
        
        # Make search request
        headers = {**DEFAULT_HEADERS, "_append": self._append_token}
        
        payload = {
            "_VillageCode": str(village_code),
            "_FromDate": from_date,
            "_ToDate": to_date,
            "EcFilter": "n",
            "firstName": party_name,
            "middleName": middle_name,
            "lastName": last_name,
            "captchaID": captcha_id,
            "captchaCode": captcha_code
        }
        
        logger.info(f"  Searching: {party_name} in village {village_code}...")
        
        response = self.session.post(
            f"{API_URL}/NewECSearch",
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        
        result = response.json()
        
        if result.get("responseCode") != 1000:
            logger.warning(f"  API warning: {result.get('responseMessage')}")
            return []
        
        # Parse data - it comes as a JSON string
        data_str = result.get("data", "[]")
        try:
            records = json.loads(data_str) if isinstance(data_str, str) else data_str
        except json.JSONDecodeError:
            records = []
        
        logger.info(f"  Found {len(records)} records")
        return records
    
    def batch_search(
        self,
        village_codes: List[str],
        party_name: str,
        from_date: str,
        to_date: str,
        output_file: str = None,
        delay: float = 2.0
    ) -> List[Dict]:
        """
        Search across multiple villages.
        Returns all results combined.
        """
        all_results = []
        
        EXPORTS_DIR.mkdir(exist_ok=True)
        
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = EXPORTS_DIR / f"ec_search_{party_name}_{timestamp}.csv"
        else:
            output_file = Path(output_file)
        
        total = len(village_codes)
        
        print(f"\n{'=' * 60}")
        print(f"KAVERI Direct API Search")
        print(f"{'=' * 60}")
        print(f"Party Name: {party_name}")
        print(f"Date Range: {from_date} to {to_date}")
        print(f"Villages:   {total}")
        print(f"Output:     {output_file}")
        print(f"{'=' * 60}\n")
        
        for idx, village_code in enumerate(village_codes, 1):
            logger.info(f"[{idx}/{total}] Processing village {village_code}")
            
            try:
                results = self.search_ec(
                    village_code=village_code,
                    party_name=party_name,
                    from_date=from_date,
                    to_date=to_date
                )
                
                # Add village code to each result
                for r in results:
                    r["_search_village_code"] = village_code
                
                all_results.extend(results)
                
                # Save incrementally
                if results:
                    self._append_to_csv(output_file, results)
                
            except Exception as e:
                logger.error(f"  Error: {e}")
            
            # Rate limiting
            if idx < total:
                time.sleep(delay)
        
        print(f"\n{'=' * 60}")
        print(f"SEARCH COMPLETE")
        print(f"{'=' * 60}")
        print(f"Total Records: {len(all_results)}")
        print(f"Output File:   {output_file}")
        print(f"{'=' * 60}\n")
        
        return all_results
    
    def _append_to_csv(self, filepath: Path, records: List[Dict]):
        """Append records to CSV file"""
        if not records:
            return
        
        file_exists = filepath.exists()
        
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=records[0].keys())
            
            if not file_exists:
                writer.writeheader()
            
            writer.writerows(records)


def get_villages_from_db(
    district_code: int = None,
    taluk_code: int = None,
    hobli_code: int = None
) -> List[str]:
    """Get village codes from the indexed database"""
    import sqlite3
    
    if not LOCATIONS_DB.exists():
        logger.error(f"Database not found: {LOCATIONS_DB}")
        logger.error("Run 'python kaveri_api_indexer.py index' first")
        return []
    
    conn = sqlite3.connect(LOCATIONS_DB)
    cursor = conn.cursor()
    
    query = """
        SELECT DISTINCT v.village_code 
        FROM villages v
        JOIN hoblis h ON v.hobli_code = h.hobli_code
        JOIN talukas t ON h.taluk_code = t.taluk_code
        JOIN districts d ON t.district_code = d.district_code
        WHERE 1=1
    """
    params = []
    
    if district_code:
        query += " AND d.district_code = ?"
        params.append(district_code)
    
    if taluk_code:
        query += " AND t.taluk_code = ?"
        params.append(taluk_code)
    
    if hobli_code:
        query += " AND h.hobli_code = ?"
        params.append(hobli_code)
    
    cursor.execute(query, params)
    village_codes = [str(row[0]) for row in cursor.fetchall()]
    
    conn.close()
    
    logger.info(f"Found {len(village_codes)} villages matching criteria")
    return village_codes


def main():
    parser = argparse.ArgumentParser(
        description="KAVERI Direct API Search Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Login and save session
  python kaveri_direct_api.py --login

  # Search with auto CAPTCHA (requires CAPTCHA_API_KEY env var)
  python kaveri_direct_api.py --party "KRISHNAPPA" --district 11

  # Search specific villages
  python kaveri_direct_api.py --party "SHIVA" --villages 15305,15342,15321

  # Manual CAPTCHA mode (no API key)
  python kaveri_direct_api.py --party "KUMAR" --hobli 406 --manual
        """
    )
    
    parser.add_argument("--login", action="store_true",
                        help="Open browser for login and session extraction")
    parser.add_argument("--party", type=str,
                        help="Party name to search")
    parser.add_argument("--from-date", type=str, default="2003-01-01",
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", type=str, default=None,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--district", type=int,
                        help="District code to search")
    parser.add_argument("--taluk", type=int,
                        help="Taluk code to search")
    parser.add_argument("--hobli", type=int,
                        help="Hobli code to search")
    parser.add_argument("--villages", type=str,
                        help="Comma-separated village codes")
    parser.add_argument("--output", type=str,
                        help="Output CSV file path")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Delay between requests (seconds)")
    parser.add_argument("--manual", action="store_true",
                        help="Use manual CAPTCHA solving instead of API")
    parser.add_argument("--captcha-service", type=str, default="2captcha",
                        choices=["2captcha", "anticaptcha"],
                        help="CAPTCHA solving service")
    
    args = parser.parse_args()
    
    # Default to-date to today
    if not args.to_date:
        args.to_date = datetime.now().strftime("%Y-%m-%d")
    
    # Get CAPTCHA API key
    captcha_api_key = None if args.manual else os.environ.get("CAPTCHA_API_KEY")
    
    if not args.manual and not captcha_api_key:
        print("\n⚠️  No CAPTCHA_API_KEY environment variable found.")
        print("   Set it with: export CAPTCHA_API_KEY='your_key'")
        print("   Or use --manual flag for manual CAPTCHA solving.\n")
    
    # Initialize client
    client = KaveriDirectAPI(
        captcha_api_key=captcha_api_key,
        captcha_service=args.captcha_service
    )
    
    # Handle login
    if args.login:
        success = client.login_via_browser()
        if success:
            print("\n✅ Login successful! Session saved.")
            print("   You can now run searches without --login")
        else:
            print("\n❌ Login failed. Please try again.")
        return
    
    # Handle search
    if args.party:
        # Get village codes
        if args.villages:
            village_codes = [v.strip() for v in args.villages.split(",")]
        else:
            village_codes = get_villages_from_db(
                district_code=args.district,
                taluk_code=args.taluk,
                hobli_code=args.hobli
            )
        
        if not village_codes:
            print("❌ No villages found. Specify --villages or location filters.")
            return
        
        # Run batch search
        results = client.batch_search(
            village_codes=village_codes,
            party_name=args.party,
            from_date=args.from_date,
            to_date=args.to_date,
            output_file=args.output,
            delay=args.delay
        )
        
        print(f"\n✅ Search complete! Found {len(results)} records.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

