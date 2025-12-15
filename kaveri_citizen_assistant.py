"""
KAVERI Citizen Assistant (prototype)

- Builds a full location hierarchy database from public KAVERI APIs.
- Provides CLI utilities to refresh locations and export CSV.
- Includes a Selenium search skeleton for manual captcha/OTP flows.

Usage examples:
  python kaveri_citizen_assistant.py build-locations
  python kaveri_citizen_assistant.py export-locations --out locations.csv
  python kaveri_citizen_assistant.py search --username USER --password PASS --party "SHIVA"

Note: Login and search require manual captcha and OTP entry. Element
locators are placeholders and may need to be updated from the live site.
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import requests
from requests import Session

# Fix Windows console encoding for Kannada/Unicode characters
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        # Python < 3.7 fallback
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    webdriver = None  # type: ignore
    SELENIUM_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

BASE_URL = "https://kaveri.karnataka.gov.in"
DB_PATH = Path("location_hierarchy.db")
JSON_PATH = Path("location_hierarchy.json")
EXPORTS_DIR = Path("exports")
EXPORTS_DIR.mkdir(exist_ok=True)


def _post_json(session: Session, path: str, payload: Dict, timeout: int = 30) -> Any:
    """Make a POST request and return JSON response."""
    url = f"{BASE_URL}{path}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        resp = session.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed for {path}: {e}")
        raise


def build_location_hierarchy(session: Optional[Session] = None) -> Dict[str, List[Dict]]:
    """Fetch complete location hierarchy from KAVERI APIs and persist to DB/JSON."""
    s = session or requests.Session()
    
    logger.info("Fetching districts...")
    districts = _post_json(s, "/api/GetDistrictAsync", {})
    logger.info(f"Found {len(districts)} districts")
    
    talukas: List[Dict] = []
    hoblis: List[Dict] = []
    villages: List[Dict] = []
    property_types: List[Dict] = []

    # Property types (optional)
    try:
        logger.info("Fetching property types...")
        property_types = _post_json(s, "/api/GetPropertyTypeMasterAsync", {})
        logger.info(f"Found {len(property_types)} property types")
    except Exception as e:
        logger.warning(f"Could not fetch property types: {e}")
        property_types = []

    # Fetch talukas for each district
    for idx, d in enumerate(districts, 1):
        dcode = d.get("districtCode")
        dname = d.get("districtNamee", "Unknown")
        if not dcode:
            continue
        logger.info(f"[{idx}/{len(districts)}] Fetching talukas for {dname}...")
        try:
            taluka_rows = _post_json(s, "/api/GetTalukaAsync", {"districtCode": str(dcode)})
            for t in taluka_rows:
                t["districtCode"] = dcode
            talukas.extend(taluka_rows)
        except Exception as e:
            logger.error(f"Failed to fetch talukas for district {dcode}: {e}")

    logger.info(f"Found {len(talukas)} talukas total")

    # Fetch hoblis for each taluka
    for idx, t in enumerate(talukas, 1):
        tcode = t.get("talukCode")
        tname = t.get("talukNamee", "Unknown")
        if not tcode:
            continue
        if idx % 20 == 0:
            logger.info(f"[{idx}/{len(talukas)}] Fetching hoblis for {tname}...")
        try:
            hobli_rows = _post_json(s, "/api/GetHobliAsync", {"talukaCode": str(tcode)})
            for h in hobli_rows:
                h["talukCode"] = tcode
            hoblis.extend(hobli_rows)
        except Exception as e:
            logger.error(f"Failed to fetch hoblis for taluka {tcode}: {e}")

    logger.info(f"Found {len(hoblis)} hoblis total")

    # Fetch villages for each hobli
    for idx, h in enumerate(hoblis, 1):
        hcode = h.get("hoblicode")
        hname = h.get("hoblinamee", "Unknown")
        if not hcode:
            continue
        if idx % 100 == 0:
            logger.info(f"[{idx}/{len(hoblis)}] Fetching villages for {hname}...")
        try:
            village_rows = _post_json(s, "/api/GetVillageAsync", {"hobliCode": str(hcode)})
            for v in village_rows:
                v["hobliCode"] = hcode
            villages.extend(village_rows)
        except Exception as e:
            logger.error(f"Failed to fetch villages for hobli {hcode}: {e}")

    logger.info(f"Found {len(villages)} villages total")

    data = {
        "districts": districts,
        "talukas": talukas,
        "hoblis": hoblis,
        "villages": villages,
        "property_types": property_types,
    }
    
    # Save to JSON
    logger.info(f"Saving to {JSON_PATH}...")
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # Save to SQLite
    logger.info(f"Saving to {DB_PATH}...")
    _write_sqlite(data)
    
    logger.info("Location hierarchy build complete!")
    return data


def _write_sqlite(data: Dict[str, List[Dict]]) -> None:
    """Write location hierarchy to SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Drop existing tables
    cur.execute("DROP TABLE IF EXISTS districts")
    cur.execute("DROP TABLE IF EXISTS talukas")
    cur.execute("DROP TABLE IF EXISTS hoblis")
    cur.execute("DROP TABLE IF EXISTS villages")
    cur.execute("DROP TABLE IF EXISTS property_types")

    # Create tables
    cur.execute(
        """
        CREATE TABLE districts (
            districtCode INTEGER PRIMARY KEY,
            districtNamee TEXT,
            districtNamek TEXT,
            bhoomiDistrictCode TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE talukas (
            talukCode INTEGER PRIMARY KEY,
            talukNamee TEXT,
            talukNamek TEXT,
            unit TEXT,
            districtCode INTEGER,
            FOREIGN KEY (districtCode) REFERENCES districts(districtCode)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE hoblis (
            hoblicode INTEGER PRIMARY KEY,
            hoblinamee TEXT,
            hoblinamek TEXT,
            bhoomitalukcode INTEGER,
            bhoomiDistrictCode TEXT,
            bhoomihoblicode INTEGER,
            talukCode INTEGER,
            FOREIGN KEY (talukCode) REFERENCES talukas(talukCode)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE villages (
            villagecode INTEGER PRIMARY KEY,
            villagenamee TEXT,
            villagenamek TEXT,
            ulbcode INTEGER,
            sroCode INTEGER,
            bhoomitalukcode INTEGER,
            bhoomiDistrictCode TEXT,
            bhoomivillagecode INTEGER,
            isurban BOOLEAN,
            hobliCode INTEGER,
            FOREIGN KEY (hobliCode) REFERENCES hoblis(hoblicode)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS property_types (
            propertytypeid INTEGER PRIMARY KEY,
            typeNameEnglish TEXT,
            typeNameKannada TEXT
        )
        """
    )

    # Insert data
    cur.executemany(
        "INSERT OR REPLACE INTO districts VALUES (?, ?, ?, ?)",
        [
            (
                d.get("districtCode"),
                d.get("districtNamee"),
                d.get("districtNamek"),
                d.get("bhoomiDistrictCode"),
            )
            for d in data["districts"]
        ],
    )
    cur.executemany(
        "INSERT OR REPLACE INTO talukas VALUES (?, ?, ?, ?, ?)",
        [
            (
                t.get("talukCode"),
                t.get("talukNamee"),
                t.get("talukNamek"),
                t.get("unit"),
                t.get("districtCode"),
            )
            for t in data["talukas"]
        ],
    )
    cur.executemany(
        "INSERT OR REPLACE INTO hoblis VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                h.get("hoblicode"),
                h.get("hoblinamee"),
                h.get("hoblinamek"),
                h.get("bhoomitalukcode"),
                h.get("bhoomiDistrictCode"),
                h.get("bhoomihoblicode"),
                h.get("talukCode"),
            )
            for h in data["hoblis"]
        ],
    )
    cur.executemany(
        "INSERT OR REPLACE INTO villages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                v.get("villagecode"),
                v.get("villagenamee"),
                v.get("villagenamek"),
                v.get("ulbcode"),
                v.get("sroCode"),
                v.get("bhoomitalukcode"),
                v.get("bhoomiDistrictCode"),
                v.get("bhoomivillagecode"),
                v.get("isurban"),
                v.get("hobliCode"),
            )
            for v in data["villages"]
        ],
    )
    
    # Insert property types if available
    if data.get("property_types"):
        cur.executemany(
            "INSERT OR REPLACE INTO property_types VALUES (?, ?, ?)",
            [
                (
                    p.get("propertytypeid"),
                    p.get("typeNameEnglish"),
                    p.get("typeNameKannada"),
                )
                for p in data["property_types"]
            ],
        )
    
    # Create indices for faster queries
    cur.execute("CREATE INDEX IF NOT EXISTS idx_talukas_district ON talukas(districtCode)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hoblis_taluk ON hoblis(talukCode)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_villages_hobli ON villages(hobliCode)")
    
    conn.commit()
    conn.close()


def export_locations_csv(out_path: Path = Path("locations.csv")) -> None:
    """Export location database to CSV and XLSX files."""
    if not DB_PATH.exists():
        raise SystemExit("location_hierarchy.db not found; run build-locations first.")
    
    conn = sqlite3.connect(DB_PATH)
    
    df_d = pd.read_sql_query("SELECT * FROM districts", conn)
    df_t = pd.read_sql_query("SELECT * FROM talukas", conn)
    df_h = pd.read_sql_query("SELECT * FROM hoblis", conn)
    df_v = pd.read_sql_query("SELECT * FROM villages", conn)
    
    # Handle property_types table gracefully
    try:
        df_p = pd.read_sql_query("SELECT * FROM property_types", conn)
    except Exception:
        df_p = pd.DataFrame(columns=["propertytypeid", "typeNameEnglish", "typeNameKannada"])
        logger.warning("property_types table not found or empty")
    
    with pd.ExcelWriter(out_path.with_suffix(".xlsx")) as writer:
        df_d.to_excel(writer, sheet_name="districts", index=False)
        df_t.to_excel(writer, sheet_name="talukas", index=False)
        df_h.to_excel(writer, sheet_name="hoblis", index=False)
        df_v.to_excel(writer, sheet_name="villages", index=False)
        df_p.to_excel(writer, sheet_name="property_types", index=False)
    
    df_v.to_csv(out_path, index=False, encoding='utf-8-sig')
    conn.close()
    logger.info(f"Exported to {out_path} and {out_path.with_suffix('.xlsx')}")


# ---------- Location access helpers ----------


class LocationRepo:
    """Repository for accessing location hierarchy data."""
    
    def __init__(self, db_path: Path = DB_PATH):
        if not db_path.exists():
            raise SystemExit("location_hierarchy.db not found; run build-locations first.")
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def districts(self) -> List[Tuple[int, str]]:
        """Get all districts ordered by name."""
        cur = self.conn.execute(
            "SELECT districtCode, districtNamee FROM districts WHERE districtCode > 0 ORDER BY districtNamee"
        )
        return [(int(r[0]), r[1]) for r in cur.fetchall()]

    def talukas(self, district_code: Optional[int] = None) -> List[Tuple[int, str, int]]:
        """Get talukas, optionally filtered by district."""
        if district_code:
            cur = self.conn.execute(
                "SELECT talukCode, talukNamee, districtCode FROM talukas WHERE districtCode=? ORDER BY talukNamee",
                (district_code,),
            )
        else:
            cur = self.conn.execute(
                "SELECT talukCode, talukNamee, districtCode FROM talukas ORDER BY talukNamee"
            )
        return [(int(r[0]), r[1], int(r[2])) for r in cur.fetchall()]

    def hoblis(self, taluk_code: Optional[int] = None) -> List[Tuple[int, str, int]]:
        """Get hoblis, optionally filtered by taluk."""
        if taluk_code:
            cur = self.conn.execute(
                "SELECT hoblicode, hoblinamee, talukCode FROM hoblis WHERE talukCode=? ORDER BY hoblinamee",
                (taluk_code,),
            )
        else:
            cur = self.conn.execute(
                "SELECT hoblicode, hoblinamee, talukCode FROM hoblis ORDER BY hoblinamee"
            )
        return [(int(r[0]), r[1], int(r[2])) for r in cur.fetchall()]

    def villages(self, hobli_code: Optional[int] = None) -> List[Tuple[int, str, int]]:
        """Get villages, optionally filtered by hobli."""
        if hobli_code:
            cur = self.conn.execute(
                "SELECT villagecode, villagenamee, hobliCode FROM villages WHERE hobliCode=? ORDER BY villagenamee",
                (hobli_code,),
            )
        else:
            cur = self.conn.execute(
                "SELECT villagecode, villagenamee, hobliCode FROM villages ORDER BY villagenamee"
            )
        return [(int(r[0]), r[1], int(r[2])) for r in cur.fetchall()]

    def property_types(self) -> List[Tuple[int, str]]:
        """Get property types."""
        try:
            cur = self.conn.execute(
                "SELECT propertytypeid, typeNameEnglish FROM property_types WHERE propertytypeid IS NOT NULL ORDER BY typeNameEnglish"
            )
            return [(int(r[0]), r[1]) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            return []

    def get_village_by_code(self, village_code: int) -> Optional[Dict]:
        """Get village details by code."""
        cur = self.conn.execute(
            "SELECT * FROM villages WHERE villagecode=?", (village_code,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_full_hierarchy(self, village_code: int) -> Optional[Dict]:
        """Get full location hierarchy for a village."""
        cur = self.conn.execute("""
            SELECT 
                v.villagecode, v.villagenamee,
                h.hoblicode, h.hoblinamee,
                t.talukCode, t.talukNamee,
                d.districtCode, d.districtNamee
            FROM villages v
            JOIN hoblis h ON v.hobliCode = h.hoblicode
            JOIN talukas t ON h.talukCode = t.talukCode
            JOIN districts d ON t.districtCode = d.districtCode
            WHERE v.villagecode = ?
        """, (village_code,))
        row = cur.fetchone()
        if row:
            return {
                "village_code": row[0], "village_name": row[1],
                "hobli_code": row[2], "hobli_name": row[3],
                "taluk_code": row[4], "taluk_name": row[5],
                "district_code": row[6], "district_name": row[7],
            }
        return None

    def close(self):
        """Close database connection."""
        self.conn.close()


# ---------- Selenium search skeleton ----------

@dataclass
class SearchConfig:
    """Configuration for KAVERI search."""
    username: str
    password: str
    party_name: str
    from_date: str = "2003-01-01"
    to_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    district_code: Optional[int] = None
    taluk_code: Optional[int] = None
    hobli_code: Optional[int] = None
    village_code: Optional[int] = None
    all_taluks: bool = False
    all_hoblis: bool = False
    all_villages: bool = False
    property_type_id: Optional[int] = None


class KaveriSearchBot:
    """Selenium-based bot for KAVERI portal searches."""
    
    def __init__(self, headless: bool = False, wait_timeout: int = 30):
        if not SELENIUM_AVAILABLE:
            raise SystemExit("Install selenium and webdriver-manager to use the bot: pip install selenium webdriver-manager")
        
        import tempfile
        
        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        
        # Use a fresh Chrome profile to avoid conflicts
        self._temp_profile_dir = tempfile.mkdtemp(prefix="kaveri_chrome_")
        opts.add_argument(f"--user-data-dir={self._temp_profile_dir}")
        
        # Minimal stable options for macOS
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        
        logger.info("Initializing Chrome WebDriver...")
        logger.info(f"Using temp profile: {self._temp_profile_dir}")
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=opts)
            self.driver.set_page_load_timeout(60)
            self.wait = WebDriverWait(self.driver, wait_timeout)
            self.short_wait = WebDriverWait(self.driver, 5)
            logger.info("WebDriver initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize WebDriver: {e}")
            raise

    def open_portal(self):
        """Navigate to the KAVERI EC search citizen page."""
        logger.info(f"Opening {BASE_URL}/ec-search-citizen")
        self.driver.get(f"{BASE_URL}/ec-search-citizen")
        time.sleep(3)  # Allow page to load
        
        # Check for session popup immediately
        self.handle_multiple_sessions_popup()

    def login_manual_captcha(self, cfg: SearchConfig):
        """
        User-driven flow: wait for manual login and navigation.
        The user must:
        1. Log in with credentials
        2. Solve CAPTCHA
        3. Enter OTP
        4. Navigate to 'Search by Party Name'
        """
        logger.info("Waiting for manual login...")
        
        # Check for and handle "multiple sessions" popup automatically
        print("\n" + "="*60)
        print("Checking for session conflicts...")
        if self.handle_multiple_sessions_popup():
            print("✓ Cleared previous sessions automatically")
        
        print("\n" + "="*60)
        print("MANUAL STEPS REQUIRED:")
        print("1. Log in with your credentials")
        print("2. Solve the CAPTCHA")
        print("3. Enter the OTP sent to your phone/email")
        print("4. If 'Multiple sessions' popup appears, click 'Yes' to clear")
        print("5. Navigate to 'Search by Party Name (Seller/Purchaser/claimant)'")
        print("6. Ensure the search form is visible")
        print("="*60)
        input("\nPress ENTER when ready to continue...")
        
        # Check again after login in case popup appeared
        self.handle_multiple_sessions_popup()
        
        # Wait for search form to be ready
        self._wait_for_search_form()
        
        logger.info("Manual login completed, continuing with automation")

    def _wait_for_search_form(self):
        """Wait for and verify the search form is loaded."""
        print("\nVerifying search form is loaded...")
        
        # Wait up to 30 seconds for form elements
        for attempt in range(6):
            try:
                # Look for district dropdown
                selects = self.driver.find_elements(By.TAG_NAME, "select")
                inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])")
                
                logger.info(f"Page check: {len(selects)} dropdowns, {len(inputs)} text inputs")
                
                if len(selects) >= 4 and len(inputs) >= 2:
                    print(f"✓ Search form detected ({len(selects)} dropdowns, {len(inputs)} inputs)")
                    
                    # Log actual form control names for debugging
                    for sel in selects:
                        fc = sel.get_attribute('formcontrolname')
                        if fc:
                            logger.info(f"  Dropdown: formcontrolname='{fc}'")
                    
                    # Log ALL inputs to find date fields
                    for inp in inputs:
                        fc = inp.get_attribute('formcontrolname') or ''
                        name = inp.get_attribute('name') or ''
                        placeholder = inp.get_attribute('placeholder') or ''
                        inp_type = inp.get_attribute('type') or 'text'
                        
                        # Log if it has any identifying attribute
                        if fc or name or 'date' in placeholder.lower():
                            logger.info(f"  Input: fc='{fc}' name='{name}' placeholder='{placeholder}' type='{inp_type}'")
                    
                    return True
                    
                print(f"  Waiting for form... ({attempt+1}/6)")
                time.sleep(5)
                
            except Exception as e:
                logger.debug(f"Form check error: {e}")
                time.sleep(5)
        
        print("\n⚠️  WARNING: Could not verify search form. Make sure you are on:")
        print("   'Search by Party Name (Seller/Purchaser/claimant)' page")
        print("   The form should have dropdowns for District, Taluka, Hobli, Village\n")
        return False

    def search_one(
        self, 
        cfg: SearchConfig, 
        district_code: int, 
        taluk_code: int, 
        hobli_code: int, 
        village_code: int,
        district_name: str = "",
        taluk_name: str = "",
        hobli_name: str = "",
        village_name: str = ""
    ) -> List[Dict]:
        """
        Perform a single search for the given location.
        Uses codes to select dropdown values, names for logging.
        """
        location_str = f"{district_name}/{taluk_name}/{hobli_name}/{village_name}"
        logger.info(f"Starting search for: {location_str}")
        
        try:
            # Select District
            self._select_dropdown_by_value("district", str(district_code))
            time.sleep(1.5)  # Wait for taluka dropdown to populate
            
            # Select Taluka
            self._select_dropdown_by_value("taluka", str(taluk_code))
            time.sleep(1.5)  # Wait for hobli dropdown to populate
            
            # Select Hobli
            self._select_dropdown_by_value("hobli", str(hobli_code))
            time.sleep(1.5)  # Wait for village dropdown to populate
            
            # Select Village
            self._select_dropdown_by_value("village", str(village_code))
            time.sleep(0.5)
            
            # Select property type if specified
            if cfg.property_type_id:
                self._select_dropdown_by_value("propertyType", str(cfg.property_type_id))
            
            # Debug: Log form structure on first search only
            if not hasattr(self, '_form_logged'):
                self._log_form_structure()
                self._form_logged = True
            
            # Fill party name - try multiple field names
            if not self._fill_field("firstName", cfg.party_name):
                self._fill_field("partyName", cfg.party_name)
            
            # Fill date fields - handle different date formats/selectors
            self._fill_date_field("fromDate", cfg.from_date)
            self._fill_date_field("toDate", cfg.to_date)
            
            # First search: user solves CAPTCHA manually, we save the code
            # Subsequent searches: re-enter same CAPTCHA and auto-click
            if not hasattr(self, '_captcha_code'):
                print(f"\n>>> Solve the CAPTCHA and click SEARCH button manually...")
                print(f">>> Then press ENTER here (CAPTCHA will be reused for remaining searches)")
                input()
                # Save the CAPTCHA code for reuse
                try:
                    captcha_input = self.driver.find_element(By.CSS_SELECTOR, 
                        "input[formcontrolname='captchacode'], input[name='captchacode']")
                    self._captcha_code = captcha_input.get_attribute('value')
                    if self._captcha_code:
                        logger.info(f"Saved CAPTCHA code for reuse: {self._captcha_code}")
                except:
                    self._captcha_code = None
            else:
                # Re-enter saved CAPTCHA and auto-click search
                print(f"   Auto-searching with saved CAPTCHA...")
                if self._captcha_code:
                    try:
                        captcha_input = self.driver.find_element(By.CSS_SELECTOR,
                            "input[formcontrolname='captchacode'], input[name='captchacode']")
                        captcha_input.clear()
                        captcha_input.send_keys(self._captcha_code)
                        logger.info(f"Re-entered CAPTCHA: {self._captcha_code}")
                    except Exception as e:
                        logger.warning(f"Could not re-enter CAPTCHA: {e}")
                
                self._click_search_button()
                time.sleep(4)  # Wait for results to load
            
            # Scrape results
            rows = self._scrape_results_table()
            
            # Add location metadata to each row
            for r in rows:
                r.update({
                    "district_code": district_code,
                    "district_name": district_name,
                    "taluk_code": taluk_code,
                    "taluk_name": taluk_name,
                    "hobli_code": hobli_code,
                    "hobli_name": hobli_name,
                    "village_code": village_code,
                    "village_name": village_name,
                    "party_name": cfg.party_name,
                    "from_date": cfg.from_date,
                    "to_date": cfg.to_date,
                })
            
            logger.info(f"Found {len(rows)} results for {location_str}")
            return rows
            
        except Exception as e:
            logger.error(f"Search failed for {location_str}: {e}")
            return []

    def _select_dropdown_by_value(self, field_name: str, value: str):
        """Select a dropdown option by value using multiple selector strategies."""
        # Map field names to possible formcontrolname values
        field_aliases = {
            'district': ['district', 'districtcode', 'districtCode', 'District'],
            'taluka': ['taluka', 'talukacode', 'taluk', 'talukCode', 'Taluka'],
            'hobli': ['hobli', 'hoblicode', 'hobliCode', 'Hobli'],
            'village': ['village', 'villagecode', 'villageCode', 'Village'],
            'propertyType': ['propertyType', 'propertytype', 'PropertyType'],
        }
        
        # Build list of possible selectors
        selectors = []
        aliases = field_aliases.get(field_name, [field_name])
        
        for alias in aliases:
            selectors.extend([
                f"select[formcontrolname='{alias}']",
                f"select[formcontrolname='{alias.lower()}']",
                f"select[name='{alias}']",
                f"select[id*='{alias}' i]",
            ])
        
        for selector in selectors:
            try:
                element = self.short_wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                select = Select(element)
                
                # Log available options for debugging
                options = [(o.get_attribute('value'), o.text) for o in select.options[:5]]
                logger.debug(f"Dropdown {field_name} options (first 5): {options}")
                
                # Try by value first
                try:
                    select.select_by_value(value)
                    logger.info(f"✓ Selected {field_name} = {value}")
                    return True
                except:
                    pass
                
                # Try finding option that contains the value
                for option in select.options:
                    opt_val = option.get_attribute('value')
                    if opt_val == value or opt_val == str(value):
                        option.click()
                        logger.info(f"✓ Selected {field_name} = {value} (by option click)")
                        return True
                    
            except Exception as e:
                logger.debug(f"Selector '{selector}' failed: {e}")
                continue
        
        # Fallback: find by position (district=0, taluka=1, hobli=2, village=3)
        position_map = {'district': 0, 'taluka': 1, 'hobli': 2, 'village': 3, 'propertyType': 4}
        if field_name in position_map:
            try:
                all_selects = self.driver.find_elements(By.TAG_NAME, "select")
                if len(all_selects) > position_map[field_name]:
                    element = all_selects[position_map[field_name]]
                    select = Select(element)
                    select.select_by_value(value)
                    logger.info(f"✓ Selected {field_name} = {value} (by position)")
                    return True
            except Exception as e:
                logger.debug(f"Position fallback failed: {e}")
        
        logger.warning(f"Could not select dropdown {field_name} by value {value}")
        return False

    def _fill_field(self, field_name: str, value: str):
        """Fill an input field using multiple selector strategies with Angular support."""
        # CSS selectors to try (lowercase first as Angular typically uses lowercase)
        css_selectors = [
            f"input[formcontrolname='{field_name.lower()}']",
            f"input[formcontrolname='{field_name}']",
            f"input[name='{field_name}']",
            f"input#{field_name}",
            f"input[id*='{field_name}']",
            f"input[placeholder*='{field_name}' i]",
        ]
        
        for selector in css_selectors:
            try:
                element = self.short_wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                
                # Click to focus
                element.click()
                element.clear()
                
                # Use JavaScript to set value with proper Angular event triggering
                self.driver.execute_script("""
                    var input = arguments[0];
                    var value = arguments[1];
                    
                    input.value = '';
                    input.value = value;
                    
                    // Trigger events for Angular reactive forms
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                """, element, value)
                
                # Verify
                actual = element.get_attribute('value')
                if actual == value:
                    logger.info(f"✓ Filled {field_name} = '{value}' (verified)")
                    return True
                else:
                    # Fallback to send_keys
                    element.clear()
                    element.send_keys(value)
                    logger.info(f"Filled {field_name} with '{value}' using CSS: {selector}")
                    return True
                    
            except Exception:
                continue
        
        logger.warning(f"Could not fill field {field_name}")
        return False

    def _fill_date_field(self, field_name: str, date_value: str):
        """Fill a date field - handles Angular datepickers with proper event triggering."""
        # Map common field names to possible form control names
        field_aliases = {
            'fromDate': ['fromdate', 'fromDate', 'from_date', 'startdate', 'startDate', 'from'],
            'toDate': ['todate', 'toDate', 'to_date', 'enddate', 'endDate', 'to'],
        }
        
        aliases = field_aliases.get(field_name, [field_name, field_name.lower()])
        
        # Build selectors
        selectors = []
        for alias in aliases:
            selectors.extend([
                f"input[formcontrolname='{alias}']",
                f"input[name='{alias}']",
                f"input[id='{alias}']",
                f"input[id*='{alias}' i]",
                f"input[placeholder*='date' i][placeholder*='{alias[:4]}' i]",
            ])
        
        # Also try by placeholder text
        if 'from' in field_name.lower():
            selectors.append("input[placeholder*='From' i]")
            selectors.append("input[placeholder*='Start' i]")
        elif 'to' in field_name.lower():
            selectors.append("input[placeholder*='To' i]")
            selectors.append("input[placeholder*='End' i]")
        
        for selector in selectors:
            try:
                date_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                if not date_input.is_displayed():
                    continue
                    
                # Clear and set value
                date_input.click()
                time.sleep(0.2)
                date_input.clear()
                
                # Use JavaScript for Angular
                self.driver.execute_script("""
                    var input = arguments[0];
                    var value = arguments[1];
                    input.value = '';
                    input.value = value;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new Event('blur', { bubbles: true }));
                """, date_input, date_value)
                
                actual = date_input.get_attribute('value')
                if actual:
                    logger.info(f"✓ Set {field_name} = '{actual}'")
                    return True
                    
            except Exception:
                continue
        
        # Fallback: find date inputs by position (fromDate = first date, toDate = second)
        try:
            date_inputs = self.driver.find_elements(By.CSS_SELECTOR, 
                "input[type='date'], input[placeholder*='date' i], input[formcontrolname*='date' i]")
            
            if not date_inputs:
                # Try finding inputs near date labels
                all_inputs = self.driver.find_elements(By.TAG_NAME, "input")
                date_inputs = [i for i in all_inputs if 'date' in (i.get_attribute('placeholder') or '').lower()]
            
            idx = 0 if 'from' in field_name.lower() else 1
            if len(date_inputs) > idx:
                date_input = date_inputs[idx]
                date_input.click()
                date_input.clear()
                date_input.send_keys(date_value)
                logger.info(f"✓ Set {field_name} = '{date_value}' (by position)")
                return True
        except Exception as e:
            logger.debug(f"Date position fallback failed: {e}")
        
        # Don't log warning if we might have actually filled it
        logger.debug(f"Date field {field_name} selector not found - may need manual entry")
        return False

    def _log_form_structure(self):
        """Log the form structure to help debug selectors."""
        try:
            # Log all select dropdowns
            selects = self.driver.find_elements(By.TAG_NAME, "select")
            logger.info(f"Found {len(selects)} dropdowns:")
            for sel in selects:
                attrs = {
                    'formcontrolname': sel.get_attribute('formcontrolname'),
                    'name': sel.get_attribute('name'),
                    'id': sel.get_attribute('id'),
                }
                logger.debug(f"  Dropdown: {attrs}")
            
            # Log all text inputs
            inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])")
            logger.info(f"Found {len(inputs)} text inputs:")
            for inp in inputs:
                attrs = {
                    'formcontrolname': inp.get_attribute('formcontrolname'),
                    'name': inp.get_attribute('name'),
                    'id': inp.get_attribute('id'),
                    'placeholder': inp.get_attribute('placeholder'),
                }
                logger.debug(f"  Input: {attrs}")
                
        except Exception as e:
            logger.debug(f"Could not log form structure: {e}")

    def _click_search_button(self):
        """Click the search/submit button."""
        selectors = [
            "button[type='submit']",
            "button.btn-primary",
            "button[type='button'].btn-primary",
            "input[type='submit']",
        ]
        
        for selector in selectors:
            try:
                element = self.short_wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                element.click()
                logger.debug("Clicked search button")
                return
            except Exception:
                continue
        
        logger.warning("Could not click search button")

    def _scrape_results_table(self) -> List[Dict]:
        """Scrape the search results table."""
        # Wait for results to load
        time.sleep(2)
        
        # Check for "no results" messages first
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            no_result_phrases = [
                "no record found",
                "no records found", 
                "no data found",
                "no results found",
                "no matching records",
                "0 records",
            ]
            for phrase in no_result_phrases:
                if phrase in page_text:
                    logger.info("No results found for this search (detected message)")
                    return []
        except:
            pass
        
        # Table selectors - including Angular Material tables
        table_selectors = [
            "table.table",
            "table.mat-table",
            "mat-table",
            "#search-table",
            "table[id*='result']",
            "table[id*='search']",
            ".table-responsive table",
            "table.table-striped",
            "table.table-bordered",
            "table",
        ]
        
        rows = []
        
        for selector in table_selectors:
            try:
                tables = self.driver.find_elements(By.CSS_SELECTOR, selector)
                
                for table in tables:
                    # Skip small tables (likely form elements, not results)
                    try:
                        table_text = table.text.lower()
                        # Skip if this looks like the search form
                        if 'captcha' in table_text or 'search' in table_text and 'district' in table_text:
                            continue
                    except:
                        pass
                    
                    # Get headers
                    headers = []
                    try:
                        header_cells = table.find_elements(By.CSS_SELECTOR, "thead th, tr:first-child th, mat-header-cell")
                        headers = [th.text.strip() for th in header_cells if th.text.strip()]
                    except Exception:
                        pass
                    
                    # Skip tables without meaningful headers (results tables usually have headers)
                    if not headers or len(headers) < 3:
                        continue
                    
                    # Get data rows
                    data_rows = []
                    try:
                        data_rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
                        if not data_rows:
                            all_rows = table.find_elements(By.CSS_SELECTOR, "tr")
                            data_rows = all_rows[1:] if len(all_rows) > 1 else []
                    except Exception:
                        pass
                    
                    # Skip if no data rows
                    if not data_rows:
                        continue
                    
                    for tr in data_rows:
                        cells = tr.find_elements(By.CSS_SELECTOR, "td, mat-cell")
                        cell_texts = [c.text.strip() for c in cells]
                        
                        # Skip empty rows or header-like rows
                        if not any(cell_texts) or len(cell_texts) < 3:
                            continue
                        
                        if headers and len(headers) == len(cell_texts):
                            row_dict = dict(zip(headers, cell_texts))
                        else:
                            row_dict = {"columns": cell_texts}
                        
                        rows.append(row_dict)
                    
                    if rows:
                        logger.info(f"Scraped {len(rows)} results")
                        return rows
                        
            except Exception as e:
                logger.debug(f"Error with selector {selector}: {e}")
                continue
        
        # No results found in any table
        if not rows:
            logger.debug("No results table found")
        
        return rows

    def logout(self):
        """Logout from KAVERI portal to prevent multiple session issues."""
        logger.info("Logging out from KAVERI portal...")
        try:
            # Method 1: Click logout button/link
            logout_selectors = [
                "a[href*='logout']",
                "a[href*='Logout']",
                "button[onclick*='logout']",
                ".logout",
                "#logout",
                "a[title*='Logout']",
                "a[title*='Log out']",
                ".nav-link[href*='logout']",
                ".dropdown-item[href*='logout']",
            ]
            
            for selector in logout_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        if element.is_displayed():
                            element.click()
                            logger.info(f"✓ Clicked logout: {selector}")
                            time.sleep(2)
                            return True
                except:
                    continue
            
            # Method 2: Find by text
            xpath_selectors = [
                "//a[contains(text(), 'Logout')]",
                "//a[contains(text(), 'Log out')]",
                "//a[contains(text(), 'Sign out')]",
                "//button[contains(text(), 'Logout')]",
                "//span[contains(text(), 'Logout')]/ancestor::a",
                "//i[contains(@class, 'sign-out') or contains(@class, 'logout')]/ancestor::a",
            ]
            
            for xpath in xpath_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, xpath)
                    for element in elements:
                        if element.is_displayed():
                            element.click()
                            logger.info("✓ Clicked logout via XPath")
                            time.sleep(2)
                            return True
                except:
                    continue
            
            # Method 3: Look for logout in dropdown menus
            try:
                # Click user menu/profile dropdown first
                dropdown_triggers = self.driver.find_elements(By.CSS_SELECTOR, 
                    ".dropdown-toggle, .user-menu, .profile-menu, [data-toggle='dropdown']")
                for trigger in dropdown_triggers:
                    if trigger.is_displayed():
                        trigger.click()
                        time.sleep(1)
                        # Now look for logout
                        logout_links = self.driver.find_elements(By.CSS_SELECTOR, 
                            ".dropdown-menu a[href*='logout'], .dropdown-item")
                        for link in logout_links:
                            if 'logout' in link.text.lower() or 'log out' in link.text.lower():
                                link.click()
                                logger.info("✓ Clicked logout from dropdown")
                                time.sleep(2)
                                return True
            except:
                pass
            
            # Method 4: Navigate to logout URL directly
            try:
                self.driver.get(f"{BASE_URL}/logout")
                logger.info("✓ Navigated to logout URL")
                time.sleep(2)
                return True
            except:
                pass
            
            # Method 5: Clear cookies to force logout
            try:
                self.driver.delete_all_cookies()
                logger.info("✓ Cleared all cookies (forced logout)")
                return True
            except:
                pass
                
            logger.warning("Could not logout properly - session may remain active")
            return False
            
        except Exception as e:
            logger.warning(f"Logout failed: {e}")
            return False

    def handle_multiple_sessions_popup(self):
        """Handle the 'Multiple active sessions detected' popup."""
        try:
            time.sleep(2)  # Wait for popup to appear
            
            # Check if popup text is present
            page_source = self.driver.page_source.lower()
            if "multiple active session" not in page_source and "active session" not in page_source:
                logger.debug("No session popup detected")
                return False
            
            logger.info("Session popup detected - attempting to clear...")
            
            # Various selectors for the "Yes" button in different modal types
            popup_selectors = [
                # SweetAlert2 buttons
                "button.swal2-confirm",
                ".swal2-confirm",
                ".swal2-popup button.swal2-confirm",
                # Bootstrap modal buttons
                ".modal-footer button.btn-primary",
                ".modal-footer button.btn-success",
                ".modal button.btn-primary",
                # Generic buttons with Yes/OK text
                "button.btn-primary",
                "button.btn-success",
            ]
            
            # XPath selectors for text-based matching
            xpath_selectors = [
                "//button[contains(text(), 'Yes')]",
                "//button[contains(text(), 'YES')]",
                "//button[contains(text(), 'Ok')]",
                "//button[contains(text(), 'OK')]",
                "//button[contains(text(), 'Confirm')]",
                "//button[contains(text(), 'Clear')]",
                "//a[contains(text(), 'Yes')]",
                "//span[contains(text(), 'Yes')]/parent::button",
            ]
            
            # Try CSS selectors first
            for selector in popup_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        if element.is_displayed():
                            element.click()
                            logger.info(f"✓ Clicked session clear button: {selector}")
                            time.sleep(2)
                            return True
                except:
                    continue
            
            # Try XPath selectors
            for xpath in xpath_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, xpath)
                    for element in elements:
                        if element.is_displayed():
                            element.click()
                            logger.info(f"✓ Clicked session clear button via XPath")
                            time.sleep(2)
                            return True
                except:
                    continue
            
            # Last resort: find any visible button and check its text
            try:
                buttons = self.driver.find_elements(By.TAG_NAME, "button")
                for btn in buttons:
                    if btn.is_displayed():
                        text = btn.text.lower()
                        if any(word in text for word in ['yes', 'ok', 'confirm', 'clear']):
                            btn.click()
                            logger.info(f"✓ Clicked button with text: {btn.text}")
                            time.sleep(2)
                            return True
            except:
                pass
            
            logger.warning("Could not find button to clear sessions")
            print("\n⚠️  Please manually click 'Yes' to clear previous sessions!")
            return False
            
        except Exception as e:
            logger.debug(f"Session popup handling error: {e}")
            return False

    def close(self):
        """Logout and close the browser, cleanup temp profile."""
        # Always try to logout first
        self.logout()
        
        logger.info("Closing browser...")
        try:
            self.driver.quit()
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")
        
        # Cleanup temp profile directory
        if hasattr(self, '_temp_profile_dir') and self._temp_profile_dir:
            import shutil
            try:
                shutil.rmtree(self._temp_profile_dir, ignore_errors=True)
                logger.info(f"Cleaned up temp profile: {self._temp_profile_dir}")
            except Exception as e:
                logger.warning(f"Could not cleanup temp profile: {e}")

    def navigate_to_party_search(self):
        """Attempt to navigate to the party search form automatically."""
        steps = [
            ("Start new application", "//button[contains(., 'START A NEW APPLICATION')]"),
            ("Select EC card", "//img[contains(@src,'land-41_EC.png')]"),
            ("Continue", "//span[contains(., 'Continue')]"),
            ("Proceed", "//button[contains(., 'Proceed')]"),
            ("Search by Party Name", "//label[contains(., 'Search by Party Name')]"),
        ]
        
        for label, xpath in steps:
            try:
                element = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                self.driver.execute_script("arguments[0].click();", element)
                logger.info(f"Clicked: {label}")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Could not click '{label}': {e}")


def build_location_combinations(
    repo: LocationRepo, 
    cfg: SearchConfig
) -> List[Tuple[int, int, int, int, str, str, str, str]]:
    """
    Build all location combinations based on search config.
    Returns tuples of (district_code, taluk_code, hobli_code, village_code, 
                       district_name, taluk_name, hobli_name, village_name)
    """
    combos = []
    
    # Get districts to search
    district_rows = repo.districts()
    if cfg.district_code:
        district_rows = [d for d in district_rows if d[0] == cfg.district_code]
    
    for d_code, d_name in district_rows:
        # Get talukas for this district
        if cfg.all_taluks:
            # Search all talukas in this district
            taluka_rows = repo.talukas(d_code)
        else:
            taluka_rows = repo.talukas(d_code)
            if cfg.taluk_code:
                taluka_rows = [t for t in taluka_rows if t[0] == cfg.taluk_code]
        
        for t_code, t_name, _ in taluka_rows:
            # Get hoblis for this taluka
            if cfg.all_hoblis:
                hobli_rows = repo.hoblis(t_code)
            else:
                hobli_rows = repo.hoblis(t_code)
                if cfg.hobli_code:
                    hobli_rows = [h for h in hobli_rows if h[0] == cfg.hobli_code]
            
            for h_code, h_name, _ in hobli_rows:
                # Get villages for this hobli
                if cfg.all_villages:
                    village_rows = repo.villages(h_code)
                else:
                    village_rows = repo.villages(h_code)
                    if cfg.village_code:
                        village_rows = [v for v in village_rows if v[0] == cfg.village_code]
                
                for v_code, v_name, _ in village_rows:
                    combos.append((d_code, t_code, h_code, v_code, d_name, t_name, h_name, v_name))
    
    # Remove duplicates while preserving order
    seen = set()
    unique_combos = []
    for combo in combos:
        key = (combo[0], combo[1], combo[2], combo[3])  # codes only
        if key not in seen:
            seen.add(key)
            unique_combos.append(combo)
    
    if len(unique_combos) < len(combos):
        logger.info(f"Removed {len(combos) - len(unique_combos)} duplicate combinations")
    
    return unique_combos


def run_build_locations():
    """CLI command to build location hierarchy."""
    data = build_location_hierarchy()
    print(
        f"\nBuilt hierarchy:\n"
        f"  - {len(data['districts'])} districts\n"
        f"  - {len(data['talukas'])} talukas\n"
        f"  - {len(data['hoblis'])} hoblis\n"
        f"  - {len(data['villages'])} villages\n"
        f"  - {len(data.get('property_types', []))} property types\n"
    )
    print(f"Saved to {DB_PATH} and {JSON_PATH}")


def run_search(args):
    """CLI command to run search."""
    cfg = SearchConfig(
        username=args.username,
        password=args.password,
        party_name=args.party,
        district_code=args.district,
        taluk_code=args.taluka,
        hobli_code=args.hobli,
        village_code=args.village,
        all_taluks=args.all_taluks,
        all_hoblis=args.all_hoblis,
        all_villages=args.all_villages,
        from_date=args.from_date,
        to_date=args.to_date,
        property_type_id=args.property_type,
    )

    if args.api_direct:
        run_api_direct_search(cfg, args)
        return

    repo = LocationRepo()
    combinations = build_location_combinations(repo, cfg)
    
    if not combinations:
        print("No location combinations to search. Check your filters.")
        repo.close()
        return
    
    print(f"\nWill search {len(combinations)} location combinations...")
    
    bot = KaveriSearchBot(headless=args.headless)
    bot.open_portal()
    bot.login_manual_captcha(cfg)
    
    all_rows: List[Dict] = []
    searches_completed = 0
    
    try:
        for idx, combo in enumerate(combinations, 1):
            d_code, t_code, h_code, v_code, d_name, t_name, h_name, v_name = combo
            
            print(f"\n{'='*60}")
            print(f"[{idx}/{len(combinations)}] {d_name} / {t_name} / {h_name} / {v_name}")
            print(f"{'='*60}")
            
            rows = bot.search_one(
                cfg, d_code, t_code, h_code, v_code,
                d_name, t_name, h_name, v_name
            )
            all_rows.extend(rows)
            searches_completed += 1
            
            # Show running total
            print(f"📊 Running total: {len(all_rows)} results from {searches_completed} searches")
            
            # If more searches remaining, give user option to continue
            if idx < len(combinations):
                remaining = len(combinations) - idx
                print(f"\n⏳ {remaining} more location(s) to search...")
                print("   (Press Ctrl+C to stop and save current results)")
                time.sleep(1)  # Brief pause between searches
                
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Search interrupted by user after {searches_completed} searches")
        print(f"   Saving {len(all_rows)} results collected so far...")
        
    finally:
        print("\nLogging out and cleaning up...")
        bot.close()  # This now includes logout
        repo.close()
        print("✓ Logged out successfully")

    # Save results - always create CSV even if empty (for tracking)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = EXPORTS_DIR / f"search_results_{timestamp}.csv"
    
    print(f"\n{'='*60}")
    print(f"SEARCH COMPLETED")
    print(f"{'='*60}")
    print(f"Total rows scraped: {len(all_rows)}")
    
    if all_rows:
        # Flatten dynamic columns
        records = []
        for r in all_rows:
            base = {k: v for k, v in r.items() if k != "columns"}
            columns = r.get("columns", [])
            for i, val in enumerate(columns):
                base[f"col_{i+1}"] = val
            records.append(base)
        
        df = pd.DataFrame(records)
        df.to_csv(out_csv, index=False, encoding='utf-8-sig')
        
        # Also save as Excel for easier viewing
        try:
            xlsx_path = out_csv.with_suffix('.xlsx')
            df.to_excel(xlsx_path, index=False)
            print(f"✓ Saved {len(records)} rows to:")
            print(f"  CSV:   {out_csv}")
            print(f"  Excel: {xlsx_path}")
        except Exception as e:
            print(f"✓ Saved {len(records)} rows to: {out_csv}")
            logger.warning(f"Could not save Excel: {e}")
        
        # Show sample of data
        print(f"\nSample data (first 3 rows):")
        print(df.head(3).to_string())
    else:
        # Create empty CSV with metadata
        meta_df = pd.DataFrame([{
            "search_date": datetime.now().isoformat(),
            "party_name": cfg.party_name,
            "from_date": cfg.from_date,
            "to_date": cfg.to_date,
            "status": "no_results_found",
            "locations_searched": len(combinations),
        }])
        meta_df.to_csv(out_csv, index=False, encoding='utf-8-sig')
        print(f"No results found. Metadata saved to: {out_csv}")
    
    print(f"{'='*60}")
    print()
    print("✅ All tasks completed successfully!")
    print("   Session logged out, browser closed.")
    print()
    print("="*60)


def run_api_direct_search(cfg: SearchConfig, args):
    """Run search directly via API (requires manual captcha)."""
    if not cfg.village_code:
        raise SystemExit("For --api-direct you must provide --village.")
    if not args.captcha_id or not args.captcha_code:
        raise SystemExit("For --api-direct provide --captcha-id and --captcha-code from the portal.")

    session = requests.Session()
    payload = {
        "_VillageCode": str(cfg.village_code),
        "_FromDate": cfg.from_date,
        "_ToDate": cfg.to_date,
        "EcFilter": "n",
        "firstName": cfg.party_name,
        "middleName": "",
        "lastName": "",
        "captchaID": args.captcha_id,
        "captchaCode": args.captcha_code,
    }
    if cfg.property_type_id:
        payload["propertyTypeId"] = cfg.property_type_id

    logger.info(f"Calling /api/NewECSearch with payload: {payload}")
    resp = _post_json(session, "/api/NewECSearch", payload)
    out_csv = EXPORTS_DIR / f"api_search_{int(time.time())}.csv"

    # Normalize response
    rows = []
    if isinstance(resp, dict) and "data" in resp:
        data = resp["data"]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = []
        if isinstance(data, list):
            rows = data
    elif isinstance(resp, list):
        rows = resp

    if rows:
        pd.DataFrame(rows).to_csv(out_csv, index=False, encoding='utf-8-sig')
        print(f"Wrote {len(rows)} rows to {out_csv}")
    else:
        print("No data returned from API search.")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="KAVERI Citizen Assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build-locations", help="Fetch and persist location hierarchy")

    export_p = sub.add_parser("export-locations", help="Export location DB to CSV/XLSX")
    export_p.add_argument("--out", default="locations.csv", help="CSV output path")

    search_p = sub.add_parser("search", help="Run Selenium search (manual captcha/OTP)")
    search_p.add_argument("--username", required=True)
    search_p.add_argument("--password", required=True)
    search_p.add_argument("--party", required=True, help="Party name to search")
    search_p.add_argument("--district", type=int, help="District code (optional)")
    search_p.add_argument("--taluka", type=int, help="Taluka code (optional)")
    search_p.add_argument("--hobli", type=int, help="Hobli code (optional)")
    search_p.add_argument("--village", type=int, help="Village code (optional)")
    search_p.add_argument("--property-type", type=int, help="Property type ID (optional)")
    search_p.add_argument("--all-taluks", action="store_true", help="Search all talukas in selected district")
    search_p.add_argument("--all-hoblis", action="store_true", help="Search all hoblis in selected taluka")
    search_p.add_argument("--all-villages", action="store_true", help="Search all villages in selected hobli")
    search_p.add_argument("--from-date", default="2003-01-01")
    search_p.add_argument("--to-date", default=datetime.now().strftime("%Y-%m-%d"))
    search_p.add_argument("--api-direct", action="store_true", help="Call /api/NewECSearch directly")
    search_p.add_argument("--captcha-id", help="Captcha ID for api-direct mode")
    search_p.add_argument("--captcha-code", help="Captcha code for api-direct mode")
    search_p.add_argument("--headless", action="store_true", help="Run Chrome headless")

    args = parser.parse_args()
    
    if args.command == "build-locations":
        run_build_locations()
    elif args.command == "export-locations":
        export_locations_csv(Path(args.out))
    elif args.command == "search":
        run_search(args)


if __name__ == "__main__":
    main()
