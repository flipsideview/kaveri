#!/usr/bin/env python3
"""
KAVERI Smart Search Tool
========================
Intelligent hybrid tool:
- Manual login (username, password, OTP)
- Automated search using browser automation + 2Captcha

This tool interacts with the actual web page, not direct API calls.
"""

import os
import sys
import json
import time
import base64
import sqlite3
import requests
import tempfile
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple
import csv

import streamlit as st

# Load .env
def load_dotenv():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_dotenv()

# Constants
BASE_URL = "https://kaveri.karnataka.gov.in"
EXPORTS_DIR = Path(__file__).parent / "exports"
LOCATIONS_DB = Path(__file__).parent / "kaveri_locations.db"

EXPORTS_DIR.mkdir(exist_ok=True)

# Page config
st.set_page_config(
    page_title="KAVERI Smart Search",
    page_icon="🔍",
    layout="wide"
)

# CSS
st.markdown("""
<style>
    .stApp { background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 100%); }
    h1, h2, h3 { color: #00d4ff !important; }
    .success-box { background: rgba(0,212,106,0.1); border-left: 4px solid #00d46a; padding: 15px; margin: 10px 0; border-radius: 8px; }
    .error-box { background: rgba(255,71,87,0.1); border-left: 4px solid #ff4757; padding: 15px; margin: 10px 0; border-radius: 8px; }
    .info-box { background: rgba(0,212,255,0.1); border-left: 4px solid #00d4ff; padding: 15px; margin: 10px 0; border-radius: 8px; }
    .stat-card { background: rgba(255,255,255,0.05); border-radius: 12px; padding: 20px; text-align: center; }
    .stat-value { font-size: 2em; font-weight: bold; color: #00d4ff; }
    .stat-label { color: #888; font-size: 0.9em; }
</style>
""", unsafe_allow_html=True)


# ============== 2Captcha Solver ==============

class CaptchaSolver:
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def solve(self, image_bytes: bytes, timeout: int = 120) -> str:
        """Solve CAPTCHA image via 2Captcha"""
        image_b64 = base64.b64encode(image_bytes).decode()
        
        # Submit
        resp = requests.post("http://2captcha.com/in.php", data={
            "key": self.api_key,
            "method": "base64",
            "body": image_b64,
            "json": 1
        })
        result = resp.json()
        
        if result.get("status") != 1:
            raise Exception(f"2Captcha submit failed: {result.get('request')}")
        
        task_id = result["request"]
        
        # Poll
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(5)
            resp = requests.get("http://2captcha.com/res.php", params={
                "key": self.api_key,
                "action": "get",
                "id": task_id,
                "json": 1
            })
            result = resp.json()
            
            if result.get("status") == 1:
                return result["request"]
            elif result.get("request") != "CAPCHA_NOT_READY":
                raise Exception(f"2Captcha error: {result.get('request')}")
        
        raise Exception("CAPTCHA solving timeout")
    
    def get_balance(self) -> float:
        try:
            resp = requests.get("http://2captcha.com/res.php", params={
                "key": self.api_key,
                "action": "getbalance",
                "json": 1
            })
            result = resp.json()
            if result.get("status") == 1:
                return float(result.get("request", 0))
        except:
            pass
        return 0.0


# ============== Browser Controller ==============

class BrowserController:
    """Controls browser for KAVERI searches"""
    
    def __init__(self):
        self.driver = None
        self.captcha_solver = None
        
        api_key = os.environ.get("CAPTCHA_API_KEY")
        if api_key:
            self.captcha_solver = CaptchaSolver(api_key)
    
    def launch(self) -> bool:
        """Launch browser"""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            
            opts = Options()
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--window-size=1400,900")
            
            temp_dir = tempfile.mkdtemp(prefix="kaveri_smart_")
            opts.add_argument(f"--user-data-dir={temp_dir}")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=opts)
            self.driver.get(f"{BASE_URL}/ec-search-citizen")
            
            return True
        except Exception as e:
            st.error(f"Failed to launch browser: {e}")
            return False
    
    def close(self):
        """Close browser"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
    
    def is_logged_in(self) -> bool:
        """Check if user is logged in and on search page"""
        if not self.driver:
            return False
        
        try:
            from selenium.webdriver.common.by import By
            
            # Check for search form elements
            selects = self.driver.find_elements(By.TAG_NAME, "select")
            
            # If we have district/taluka dropdowns, we're likely logged in
            for sel in selects:
                fc = sel.get_attribute("formcontrolname") or ""
                if "district" in fc.lower():
                    return True
            
            return False
        except:
            return False
    
    def get_current_page(self) -> str:
        """Get current page info"""
        if not self.driver:
            return "No browser"
        try:
            return self.driver.current_url
        except:
            return "Unknown"
    
    def select_dropdown(self, formcontrolname: str, value_text: str) -> bool:
        """Select a value in a dropdown by visible text"""
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import Select
            
            selects = self.driver.find_elements(By.TAG_NAME, "select")
            for sel in selects:
                fc = sel.get_attribute("formcontrolname") or ""
                if formcontrolname.lower() in fc.lower():
                    select = Select(sel)
                    for opt in select.options:
                        if value_text.lower() in opt.text.lower():
                            select.select_by_visible_text(opt.text)
                            time.sleep(1)  # Wait for dependent dropdowns to load
                            return True
            return False
        except Exception as e:
            return False
    
    def select_dropdown_by_value(self, formcontrolname: str, value: str) -> bool:
        """Select a value in a dropdown by value attribute"""
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import Select
            
            selects = self.driver.find_elements(By.TAG_NAME, "select")
            for sel in selects:
                fc = sel.get_attribute("formcontrolname") or ""
                if formcontrolname.lower() in fc.lower():
                    select = Select(sel)
                    select.select_by_value(str(value))
                    time.sleep(1)
                    return True
            return False
        except:
            return False
    
    def fill_text_field(self, formcontrolname: str, text: str) -> bool:
        """Fill a text input field"""
        try:
            from selenium.webdriver.common.by import By
            
            inputs = self.driver.find_elements(By.CSS_SELECTOR, f"input[formcontrolname='{formcontrolname}']")
            if inputs:
                inputs[0].clear()
                inputs[0].send_keys(text)
                return True
            return False
        except:
            return False
    
    def get_captcha_image(self) -> Optional[bytes]:
        """Get CAPTCHA image from page"""
        try:
            from selenium.webdriver.common.by import By
            
            # Find captcha image
            imgs = self.driver.find_elements(By.TAG_NAME, "img")
            for img in imgs:
                src = img.get_attribute("src") or ""
                if "captcha" in src.lower() or "generate" in src.lower():
                    # Get image as screenshot or fetch from src
                    return img.screenshot_as_png
            
            # Alternative: look for img with specific class or near captcha input
            captcha_imgs = self.driver.find_elements(By.CSS_SELECTOR, "img[src*='Generate']")
            if captcha_imgs:
                return captcha_imgs[0].screenshot_as_png
            
            return None
        except:
            return None
    
    def refresh_captcha(self) -> Optional[bytes]:
        """Click refresh button and get new CAPTCHA"""
        try:
            from selenium.webdriver.common.by import By
            
            # Click refresh/reload button near CAPTCHA
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                text = btn.text.lower()
                cls = (btn.get_attribute("class") or "").lower()
                if "refresh" in text or "reload" in text or "sync" in cls:
                    btn.click()
                    time.sleep(2)
                    break
            
            return self.get_captcha_image()
        except:
            return self.get_captcha_image()
    
    def solve_and_fill_captcha(self) -> bool:
        """Get CAPTCHA, solve it via 2Captcha, and fill it in"""
        if not self.captcha_solver:
            return False
        
        try:
            # Get CAPTCHA image
            captcha_img = self.refresh_captcha() or self.get_captcha_image()
            if not captcha_img:
                return False
            
            # Solve via 2Captcha
            solution = self.captcha_solver.solve(captcha_img)
            
            # Fill in the solution
            return self.fill_text_field("captchaCode", solution)
        except Exception as e:
            st.error(f"CAPTCHA error: {e}")
            return False
    
    def click_search(self) -> bool:
        """Click the search button"""
        try:
            from selenium.webdriver.common.by import By
            
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                text = btn.text.lower()
                btn_type = btn.get_attribute("type") or ""
                if "search" in text or btn_type == "submit":
                    btn.click()
                    time.sleep(3)  # Wait for results
                    return True
            return False
        except:
            return False
    
    def get_results_table(self) -> List[Dict]:
        """Scrape results from the page"""
        try:
            from selenium.webdriver.common.by import By
            
            results = []
            
            # Find tables
            tables = self.driver.find_elements(By.TAG_NAME, "table")
            
            for table in tables:
                # Skip form tables
                if "form" in (table.get_attribute("class") or "").lower():
                    continue
                
                rows = table.find_elements(By.TAG_NAME, "tr")
                if len(rows) < 2:
                    continue
                
                # Get headers
                headers = []
                header_row = rows[0]
                for th in header_row.find_elements(By.TAG_NAME, "th"):
                    headers.append(th.text.strip())
                
                if not headers:
                    # Try td in first row
                    for td in header_row.find_elements(By.TAG_NAME, "td"):
                        headers.append(td.text.strip())
                
                if not headers:
                    continue
                
                # Get data rows
                for row in rows[1:]:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= len(headers):
                        record = {}
                        for i, header in enumerate(headers):
                            if i < len(cells):
                                record[header] = cells[i].text.strip()
                        if any(record.values()):
                            results.append(record)
            
            return results
        except:
            return []
    
    def check_no_results(self) -> bool:
        """Check if page shows 'no results' message"""
        try:
            page_text = self.driver.page_source.lower()
            return "no record" in page_text or "no data" in page_text or "not found" in page_text
        except:
            return False
    
    def search_village(
        self,
        village_name: str,
        party_name: str,
        from_date: str,
        to_date: str
    ) -> Tuple[bool, List[Dict], str]:
        """
        Perform search for a specific village.
        Returns (success, results, error_message)
        """
        try:
            # Fill party name
            if not self.fill_text_field("firstName", party_name):
                return False, [], "Could not fill party name"
            
            # Fill dates
            self.fill_text_field("fromDate", from_date)
            self.fill_text_field("toDate", to_date)
            
            # Select village (it should already be in dropdown from hierarchy)
            if not self.select_dropdown("villageCode", village_name):
                return False, [], f"Could not select village: {village_name}"
            
            time.sleep(1)
            
            # Solve CAPTCHA
            if not self.solve_and_fill_captcha():
                return False, [], "CAPTCHA solving failed"
            
            # Click search
            if not self.click_search():
                return False, [], "Could not click search button"
            
            time.sleep(2)
            
            # Check for errors on page
            page_text = self.driver.page_source.lower()
            if "session" in page_text and "expired" in page_text:
                return False, [], "SESSION_EXPIRED"
            if "unauthorized" in page_text:
                return False, [], "SESSION_EXPIRED"
            
            # Check for no results
            if self.check_no_results():
                return True, [], ""
            
            # Get results
            results = self.get_results_table()
            return True, results, ""
            
        except Exception as e:
            error_msg = str(e).lower()
            if "session" in error_msg or "login" in error_msg or "unauthorized" in error_msg:
                return False, [], "SESSION_EXPIRED"
            return False, [], str(e)


# ============== Database Functions ==============

@st.cache_resource
def get_db():
    if not LOCATIONS_DB.exists():
        return None
    return sqlite3.connect(LOCATIONS_DB, check_same_thread=False)


def get_districts() -> List[Dict]:
    conn = get_db()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT district_code, district_name_en FROM districts ORDER BY district_name_en")
    return [{"code": r[0], "name": r[1]} for r in cursor.fetchall()]


def get_talukas(district_code: int) -> List[Dict]:
    conn = get_db()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT taluk_code, taluk_name_en FROM talukas WHERE district_code = ? ORDER BY taluk_name_en", (district_code,))
    return [{"code": r[0], "name": r[1]} for r in cursor.fetchall()]


def get_hoblis(taluk_code: int) -> List[Dict]:
    conn = get_db()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT hobli_code, hobli_name_en FROM hoblis WHERE taluk_code = ? ORDER BY hobli_name_en", (taluk_code,))
    return [{"code": r[0], "name": r[1]} for r in cursor.fetchall()]


def get_villages(hobli_code: int) -> List[Dict]:
    conn = get_db()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT village_code, village_name_en FROM villages WHERE hobli_code = ? ORDER BY village_name_en", (hobli_code,))
    return [{"code": r[0], "name": r[1]} for r in cursor.fetchall()]


# ============== Main App ==============

def main():
    st.title("🔍 KAVERI Smart Search")
    st.caption("Intelligent automation with manual login")
    
    # Initialize browser controller in session
    if "browser" not in st.session_state:
        st.session_state.browser = BrowserController()
    
    browser = st.session_state.browser
    
    # Sidebar
    with st.sidebar:
        st.markdown("### 📊 Status")
        
        # Browser status
        if browser.driver:
            if browser.is_logged_in():
                st.success("✅ Logged in & Ready")
            else:
                st.warning("⚠️ Browser open, not logged in")
        else:
            st.error("❌ Browser not running")
        
        # 2Captcha status
        api_key = os.environ.get("CAPTCHA_API_KEY")
        if api_key:
            if browser.captcha_solver:
                balance = browser.captcha_solver.get_balance()
                st.info(f"💰 2Captcha: ${balance:.2f}")
        else:
            st.error("❌ No CAPTCHA API key")
        
        st.divider()
        
        # Browser controls
        st.markdown("### 🌐 Browser")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🚀 Launch", use_container_width=True):
                if browser.launch():
                    st.success("Launched!")
                    st.rerun()
        with col2:
            if st.button("🗑️ Close", use_container_width=True):
                browser.close()
                st.success("Closed")
                st.rerun()
    
    # Main content
    tab1, tab2, tab3 = st.tabs(["🔐 Login", "🔍 Search", "📊 Results"])
    
    # ===== LOGIN TAB =====
    with tab1:
        st.markdown("### Step 1: Manual Login")
        
        st.markdown("""
        <div class="info-box">
            <h4>📋 Instructions</h4>
            <ol>
                <li>Click <b>Launch Browser</b> in sidebar</li>
                <li>In the browser window, complete login:
                    <ul>
                        <li>Enter username & password</li>
                        <li>Solve CAPTCHA</li>
                        <li>Enter OTP</li>
                    </ul>
                </li>
                <li>Navigate to <b>"Search by Party Name"</b> page</li>
                <li>Select your <b>District</b> and <b>Taluka</b> in the browser</li>
                <li>Come back here and go to <b>Search</b> tab</li>
            </ol>
        </div>
        """, unsafe_allow_html=True)
        
        if browser.driver:
            st.success(f"✅ Browser open: {browser.get_current_page()}")
            
            if browser.is_logged_in():
                st.success("✅ You appear to be logged in! Go to Search tab.")
            else:
                st.warning("⚠️ Complete login in the browser window")
        else:
            st.error("❌ Click 'Launch' in sidebar to start browser")
    
    # ===== SEARCH TAB =====
    with tab2:
        st.markdown("### Step 2: Configure & Run Search")
        
        if not browser.driver:
            st.error("❌ Launch browser first (sidebar)")
            st.stop()
        
        if not browser.is_logged_in():
            st.warning("⚠️ Please login first (see Login tab)")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 👤 Search Criteria")
            party_name = st.text_input("Party Name *", placeholder="e.g., KRISHNAPPA")
            
            c1, c2 = st.columns(2)
            with c1:
                from_date = st.date_input("From", value=date(2003, 1, 1))
            with c2:
                to_date = st.date_input("To", value=date.today())
        
        with col2:
            st.markdown("#### 📍 Location")
            st.info("💡 Select the same location hierarchy that you selected in the browser!")
            
            districts = get_districts()
            district_opts = {d["name"]: d["code"] for d in districts}
            selected_district = st.selectbox("District", ["--"] + list(district_opts.keys()))
            district_code = district_opts.get(selected_district)
            
            if district_code:
                talukas = get_talukas(district_code)
                taluka_opts = {t["name"]: t["code"] for t in talukas}
                selected_taluka = st.selectbox("Taluka", ["--"] + list(taluka_opts.keys()))
                taluk_code = taluka_opts.get(selected_taluka)
            else:
                taluk_code = None
                st.selectbox("Taluka", ["-- Select District --"], disabled=True)
            
            if taluk_code:
                hoblis = get_hoblis(taluk_code)
                hobli_opts = {h["name"]: h["code"] for h in hoblis}
                selected_hobli = st.selectbox("Hobli", ["--"] + list(hobli_opts.keys()))
                hobli_code = hobli_opts.get(selected_hobli)
            else:
                hobli_code = None
                st.selectbox("Hobli", ["-- Select Taluka --"], disabled=True)
        
        # Village list
        villages = []
        if hobli_code:
            villages = get_villages(hobli_code)
            st.success(f"📍 {len(villages)} villages in selected hobli")
        
        # Search button
        st.markdown("---")
        
        can_search = party_name and hobli_code and villages and browser.is_logged_in()
        
        if st.button("🚀 START SMART SEARCH", type="primary", use_container_width=True, disabled=not can_search):
            # Initialize
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = EXPORTS_DIR / f"smart_{party_name}_{timestamp}.csv"
            
            all_results = []
            errors = []
            session_expired = False
            
            # Progress
            progress = st.progress(0)
            status = st.empty()
            stats = st.empty()
            
            total = len(villages)
            
            for idx, village in enumerate(villages):
                if session_expired:
                    break
                
                progress.progress((idx + 1) / total)
                status.markdown(f"**Searching:** {village['name']} ({idx + 1}/{total})")
                
                # Perform search
                success, results, error = browser.search_village(
                    village_name=village["name"],
                    party_name=party_name,
                    from_date=from_date.strftime("%d-%m-%Y"),
                    to_date=to_date.strftime("%d-%m-%Y")
                )
                
                if error == "SESSION_EXPIRED":
                    session_expired = True
                    st.error("🛑 SESSION EXPIRED! Please login again.")
                    break
                
                if success:
                    for r in results:
                        r["_village"] = village["name"]
                    all_results.extend(results)
                    
                    # Save incrementally
                    if results:
                        exists = output_file.exists()
                        with open(output_file, "a", newline="", encoding="utf-8") as f:
                            writer = csv.DictWriter(f, fieldnames=results[0].keys())
                            if not exists:
                                writer.writeheader()
                            writer.writerows(results)
                else:
                    if error:
                        errors.append(f"{village['name']}: {error}")
                
                stats.markdown(f"**Found:** {len(all_results)} records | **Errors:** {len(errors)}")
                
                time.sleep(1)  # Rate limiting
            
            # Done
            progress.progress(1.0)
            
            if session_expired:
                status.error("❌ Search stopped - session expired")
            else:
                status.success("✅ Search complete!")
            
            # Store results
            st.session_state["results"] = all_results
            st.session_state["output_file"] = str(output_file)
            st.session_state["errors"] = errors
            
            st.balloons()
    
    # ===== RESULTS TAB =====
    with tab3:
        st.markdown("### Search Results")
        
        if "results" not in st.session_state:
            st.info("No results yet. Run a search first.")
        else:
            results = st.session_state["results"]
            output_file = st.session_state.get("output_file")
            errors = st.session_state.get("errors", [])
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Records Found", len(results))
            with col2:
                st.metric("Errors", len(errors))
            with col3:
                if output_file and Path(output_file).exists():
                    with open(output_file, "rb") as f:
                        st.download_button("📥 Download CSV", f.read(), Path(output_file).name)
            
            if results:
                import pandas as pd
                st.dataframe(pd.DataFrame(results[:100]), use_container_width=True)
            
            if errors:
                with st.expander(f"⚠️ Errors ({len(errors)})"):
                    for e in errors[:20]:
                        st.error(e)


if __name__ == "__main__":
    main()

