#!/usr/bin/env python3
"""
KAVERI Hybrid Search Tool
=========================
Expert-designed tool combining manual login with direct API search.

Flow:
1. Manual browser login (username, password, CAPTCHA, OTP)
2. Extract session token
3. Direct API search with auto CAPTCHA solving

Usage:
  streamlit run kaveri_hybrid_search.py
"""

import os
import sys
import json
import time
import base64
import sqlite3
import requests
import tempfile
import threading
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
import csv

import streamlit as st

# Load .env file
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
API_URL = f"{BASE_URL}/api"
SESSION_FILE = Path(__file__).parent / ".kaveri_session.json"
EXPORTS_DIR = Path(__file__).parent / "exports"
LOCATIONS_DB = Path(__file__).parent / "kaveri_locations.db"

EXPORTS_DIR.mkdir(exist_ok=True)

# Page config
st.set_page_config(
    page_title="KAVERI Direct Search",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for expert design
st.markdown("""
<style>
    /* Main theme */
    .stApp {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    }
    
    /* Headers */
    h1, h2, h3 {
        color: #e94560 !important;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    /* Cards */
    .css-1r6slb0, .css-12oz5g7 {
        background: rgba(255,255,255,0.05);
        border-radius: 15px;
        padding: 20px;
        border: 1px solid rgba(233, 69, 96, 0.3);
    }
    
    /* Status cards */
    .status-card {
        background: linear-gradient(135deg, rgba(233, 69, 96, 0.1), rgba(233, 69, 96, 0.05));
        border-radius: 12px;
        padding: 20px;
        margin: 10px 0;
        border-left: 4px solid #e94560;
    }
    
    .status-card.success {
        border-left-color: #00d26a;
        background: linear-gradient(135deg, rgba(0, 210, 106, 0.1), rgba(0, 210, 106, 0.05));
    }
    
    .status-card.warning {
        border-left-color: #ffc107;
        background: linear-gradient(135deg, rgba(255, 193, 7, 0.1), rgba(255, 193, 7, 0.05));
    }
    
    /* Metrics */
    .metric-container {
        background: rgba(255,255,255,0.08);
        border-radius: 10px;
        padding: 15px;
        text-align: center;
        border: 1px solid rgba(255,255,255,0.1);
    }
    
    .metric-value {
        font-size: 2.5em;
        font-weight: bold;
        color: #e94560;
    }
    
    .metric-label {
        color: #8892b0;
        font-size: 0.9em;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #e94560, #c73e54);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 12px 24px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 20px rgba(233, 69, 96, 0.4);
    }
    
    /* Progress */
    .stProgress > div > div {
        background: linear-gradient(90deg, #e94560, #ff6b6b);
    }
    
    /* Sidebar */
    .css-1d391kg {
        background: rgba(0,0,0,0.3);
    }
    
    /* Input fields */
    .stTextInput > div > div > input,
    .stSelectbox > div > div > select {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        color: white;
    }
    
    /* Tables */
    .dataframe {
        background: rgba(255,255,255,0.05) !important;
    }
    
    /* Footer */
    .footer {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: rgba(0,0,0,0.5);
        padding: 10px;
        text-align: center;
        color: #8892b0;
        font-size: 0.8em;
    }
</style>
""", unsafe_allow_html=True)


# ============== Session Management ==============

def load_session() -> Dict:
    """Load saved session from file"""
    if SESSION_FILE.exists():
        try:
            with open(SESSION_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_session(data: Dict):
    """Save session to file"""
    data["saved_at"] = datetime.now().isoformat()
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f, indent=2)


def is_session_valid() -> bool:
    """Check if we have a valid session (token or cookies)"""
    session = load_session()
    
    # Need either token or cookies
    has_token = bool(session.get("append_token"))
    has_cookies = bool(session.get("cookies"))
    
    if not has_token and not has_cookies:
        return False
    
    # Check if session is less than 1 hour old
    saved_at = session.get("saved_at")
    if saved_at:
        try:
            saved_time = datetime.fromisoformat(saved_at)
            if (datetime.now() - saved_time).seconds > 3600:
                return False
        except:
            pass
    
    return True


def get_session_info() -> dict:
    """Get session info for display"""
    session = load_session()
    return {
        "has_token": bool(session.get("append_token")),
        "token_preview": session.get("append_token", "")[:8] + "..." if session.get("append_token") else "None",
        "cookie_count": len(session.get("cookies", [])),
        "saved_at": session.get("saved_at", "Never")
    }


# ============== CAPTCHA Solver ==============

class CaptchaSolver:
    """2Captcha integration"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.submit_url = "http://2captcha.com/in.php"
        self.result_url = "http://2captcha.com/res.php"
    
    def solve(self, image_bytes: bytes, timeout: int = 120) -> str:
        """Solve CAPTCHA image"""
        image_b64 = base64.b64encode(image_bytes).decode()
        
        # Submit
        resp = requests.post(self.submit_url, data={
            "key": self.api_key,
            "method": "base64",
            "body": image_b64,
            "json": 1
        })
        result = resp.json()
        
        if result.get("status") != 1:
            raise Exception(f"Submit failed: {result.get('request')}")
        
        task_id = result["request"]
        
        # Poll for result
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(5)
            
            resp = requests.get(self.result_url, params={
                "key": self.api_key,
                "action": "get",
                "id": task_id,
                "json": 1
            })
            result = resp.json()
            
            if result.get("status") == 1:
                return result["request"]
            elif result.get("request") != "CAPCHA_NOT_READY":
                raise Exception(f"Error: {result.get('request')}")
        
        raise Exception("Timeout")
    
    def get_balance(self) -> float:
        """Get account balance"""
        try:
            resp = requests.get(self.result_url, params={
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


# ============== KAVERI API Client ==============

class KaveriAPI:
    """Direct API client for KAVERI"""
    
    def __init__(self, browser_driver=None):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        self._token = None
        self._driver = browser_driver  # Optional: use browser for requests
        self._load_session()
    
    def _load_session(self):
        """Load token and cookies from saved session"""
        saved = load_session()
        self._token = saved.get("append_token")
        
        # Load cookies
        for cookie in saved.get("cookies", []):
            self.session.cookies.set(
                cookie.get("name", ""),
                cookie.get("value", ""),
                domain=cookie.get("domain", "kaveri.karnataka.gov.in"),
                path=cookie.get("path", "/")
            )
    
    def set_driver(self, driver):
        """Set browser driver for making requests through browser"""
        self._driver = driver
    
    def set_token(self, token: str, cookies: list = None):
        """Set authentication token and cookies"""
        self._token = token
        
        # Save to file
        session_data = {"append_token": token}
        if cookies:
            session_data["cookies"] = cookies
            # Also set cookies on the session
            for cookie in cookies:
                self.session.cookies.set(
                    cookie.get("name", ""),
                    cookie.get("value", ""),
                    domain=cookie.get("domain", "kaveri.karnataka.gov.in"),
                    path=cookie.get("path", "/")
                )
        
        save_session(session_data)
    
    def _fetch_via_browser(self, url: str, method: str = "POST", payload: dict = None) -> dict:
        """Make API request through the browser using JavaScript fetch"""
        if not self._driver:
            raise Exception("No browser driver available")
        
        payload_json = json.dumps(payload or {})
        
        script = f"""
        return await fetch("{url}", {{
            method: "{method}",
            headers: {{
                "Accept": "application/json",
                "Content-Type": "application/json"
            }},
            body: {payload_json if method == "POST" else "undefined"}
        }}).then(r => r.json()).catch(e => ({{error: e.message}}));
        """
        
        try:
            result = self._driver.execute_script(f"return (async () => {{ {script} }})()")
            return result
        except Exception as e:
            return {"error": str(e)}
    
    def generate_captcha(self) -> Tuple[str, bytes]:
        """Generate CAPTCHA, returns (captcha_id, image_bytes)"""
        resp = self.session.get(f"{API_URL}/Generate")
        resp.raise_for_status()
        return resp.headers.get("i"), resp.content
    
    def test_session(self) -> Tuple[bool, str]:
        """Test if session is valid by making a simple API call"""
        try:
            headers = dict(self.session.headers)
            if self._token:
                headers["_append"] = self._token
            
            # Try to fetch districts (simple authenticated call)
            resp = self.session.post(
                f"{API_URL}/GetDistrictAsync",
                headers=headers,
                json={},
                timeout=30
            )
            
            if resp.status_code == 401:
                return False, "401 Unauthorized - Session invalid"
            
            resp.raise_for_status()
            data = resp.json()
            
            if isinstance(data, list) and len(data) > 0:
                return True, f"Session valid! Got {len(data)} districts"
            else:
                return False, "Unexpected response"
                
        except Exception as e:
            return False, str(e)
    
    def search(
        self,
        village_code: str,
        party_name: str,
        from_date: str,
        to_date: str,
        captcha_id: str,
        captcha_code: str,
        use_browser: bool = False
    ) -> List[Dict]:
        """Perform EC search"""
        payload = {
            "_VillageCode": str(village_code),
            "_FromDate": from_date,
            "_ToDate": to_date,
            "EcFilter": "n",
            "firstName": party_name,
            "middleName": "",
            "lastName": "",
            "captchaID": captcha_id,
            "captchaCode": captcha_code
        }
        
        # Try browser-based request if driver available and requested
        if use_browser and self._driver:
            try:
                result = self._fetch_via_browser(f"{API_URL}/NewECSearch", "POST", payload)
                if "error" in result:
                    raise Exception(result["error"])
                
                if result.get("responseCode") != 1000:
                    return []
                
                data_str = result.get("data", "[]")
                try:
                    return json.loads(data_str) if isinstance(data_str, str) else data_str
                except:
                    return []
            except Exception as e:
                # Fall back to requests
                pass
        
        # Use requests library
        headers = dict(self.session.headers)
        if self._token:
            headers["_append"] = self._token
        
        resp = self.session.post(
            f"{API_URL}/NewECSearch",
            headers=headers,
            json=payload,
            timeout=60
        )
        
        # Handle 401 specifically
        if resp.status_code == 401:
            raise Exception("Session expired! Please login again (Tab 1)")
        
        resp.raise_for_status()
        
        result = resp.json()
        
        if result.get("responseCode") != 1000:
            return []
        
        data_str = result.get("data", "[]")
        try:
            return json.loads(data_str) if isinstance(data_str, str) else data_str
        except:
            return []


# ============== Database Functions ==============

@st.cache_resource
def get_db_connection():
    """Get database connection"""
    if not LOCATIONS_DB.exists():
        return None
    return sqlite3.connect(LOCATIONS_DB, check_same_thread=False)


def get_districts() -> List[Dict]:
    """Get all districts"""
    conn = get_db_connection()
    if not conn:
        return []
    
    cursor = conn.cursor()
    cursor.execute("SELECT district_code, district_name_en FROM districts ORDER BY district_name_en")
    return [{"code": r[0], "name": r[1]} for r in cursor.fetchall()]


def get_talukas(district_code: int) -> List[Dict]:
    """Get talukas for district"""
    conn = get_db_connection()
    if not conn:
        return []
    
    cursor = conn.cursor()
    cursor.execute(
        "SELECT taluk_code, taluk_name_en FROM talukas WHERE district_code = ? ORDER BY taluk_name_en",
        (district_code,)
    )
    return [{"code": r[0], "name": r[1]} for r in cursor.fetchall()]


def get_hoblis(taluk_code: int) -> List[Dict]:
    """Get hoblis for taluka"""
    conn = get_db_connection()
    if not conn:
        return []
    
    cursor = conn.cursor()
    cursor.execute(
        "SELECT hobli_code, hobli_name_en FROM hoblis WHERE taluk_code = ? ORDER BY hobli_name_en",
        (taluk_code,)
    )
    return [{"code": r[0], "name": r[1]} for r in cursor.fetchall()]


def get_villages(hobli_code: int = None, taluk_code: int = None, district_code: int = None) -> List[Dict]:
    """Get villages based on filters"""
    conn = get_db_connection()
    if not conn:
        return []
    
    cursor = conn.cursor()
    
    if hobli_code:
        cursor.execute(
            "SELECT DISTINCT village_code, village_name_en FROM villages WHERE hobli_code = ? ORDER BY village_name_en",
            (hobli_code,)
        )
    elif taluk_code:
        cursor.execute("""
            SELECT DISTINCT v.village_code, v.village_name_en 
            FROM villages v
            JOIN hoblis h ON v.hobli_code = h.hobli_code
            WHERE h.taluk_code = ?
            ORDER BY v.village_name_en
        """, (taluk_code,))
    elif district_code:
        cursor.execute("""
            SELECT DISTINCT v.village_code, v.village_name_en 
            FROM villages v
            JOIN hoblis h ON v.hobli_code = h.hobli_code
            JOIN talukas t ON h.taluk_code = t.taluk_code
            WHERE t.district_code = ?
            ORDER BY v.village_name_en
        """, (district_code,))
    else:
        return []
    
    return [{"code": r[0], "name": r[1]} for r in cursor.fetchall()]


def count_villages(hobli_code: int = None, taluk_code: int = None, district_code: int = None) -> int:
    """Count villages based on filters"""
    return len(get_villages(hobli_code, taluk_code, district_code))


# ============== Browser Login ==============

def launch_login_browser():
    """Launch browser for manual login"""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from webdriver_manager.chrome import ChromeDriverManager
        
        opts = Options()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        
        temp_dir = tempfile.mkdtemp(prefix="kaveri_")
        opts.add_argument(f"--user-data-dir={temp_dir}")
        
        # Enable network logging to capture the token
        opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        
        driver.get(f"{BASE_URL}/ec-search-citizen")
        
        return driver, temp_dir
        
    except Exception as e:
        st.error(f"Failed to launch browser: {e}")
        return None, None


def extract_session_from_browser(driver) -> dict:
    """
    Extract full session (token + cookies) from browser.
    Returns dict with 'token' and 'cookies' or empty dict if failed.
    """
    result = {"token": None, "cookies": []}
    
    try:
        from selenium.webdriver.common.by import By
        import json
        
        # Step 1: Get all cookies from browser
        try:
            cookies = driver.get_cookies()
            result["cookies"] = cookies
        except:
            pass
        
        # Step 2: Try to get _append token from performance logs
        try:
            logs = driver.get_log("performance")
            for log in reversed(logs):  # Check most recent first
                try:
                    message = json.loads(log["message"])
                    msg = message.get("message", {})
                    if msg.get("method") == "Network.requestWillBeSent":
                        headers = msg.get("params", {}).get("request", {}).get("headers", {})
                        if "_append" in headers:
                            result["token"] = headers["_append"]
                            break
                except:
                    continue
        except:
            pass
        
        # Step 3: If no token yet, try localStorage/sessionStorage
        if not result["token"]:
            try:
                token = driver.execute_script("""
                    // Try localStorage
                    for (let key of Object.keys(localStorage)) {
                        let val = localStorage.getItem(key);
                        if (val && val.length === 32 && /^[a-f0-9]+$/.test(val)) {
                            return val;
                        }
                    }
                    // Try sessionStorage  
                    for (let key of Object.keys(sessionStorage)) {
                        let val = sessionStorage.getItem(key);
                        if (val && val.length === 32 && /^[a-f0-9]+$/.test(val)) {
                            return val;
                        }
                    }
                    return null;
                """)
                if token:
                    result["token"] = token
            except:
                pass
        
        # Step 4: If still no token, trigger a dropdown to capture it
        if not result["token"]:
            try:
                selects = driver.find_elements(By.TAG_NAME, "select")
                for select in selects:
                    fc = select.get_attribute("formcontrolname") or ""
                    if "district" in fc.lower():
                        from selenium.webdriver.support.ui import Select
                        sel = Select(select)
                        if len(sel.options) > 1:
                            sel.select_by_index(1)
                            time.sleep(2)
                            
                            logs = driver.get_log("performance")
                            for log in reversed(logs):
                                try:
                                    message = json.loads(log["message"])
                                    msg = message.get("message", {})
                                    if msg.get("method") == "Network.requestWillBeSent":
                                        headers = msg.get("params", {}).get("request", {}).get("headers", {})
                                        if "_append" in headers:
                                            result["token"] = headers["_append"]
                                            break
                                except:
                                    continue
                        break
            except:
                pass
        
        return result
        
    except Exception as e:
        return result


# Keep old function name for backward compatibility
def extract_token_from_browser(driver) -> str:
    """Extract just the token (legacy function)"""
    result = extract_session_from_browser(driver)
    return result.get("token")


# ============== Main App ==============

def main():
    # Header
    st.markdown("""
    <div style="text-align: center; padding: 20px 0;">
        <h1 style="font-size: 2.5em; margin-bottom: 0;">🏛️ KAVERI Direct Search</h1>
        <p style="color: #8892b0; font-size: 1.1em;">Hybrid Search Tool • Manual Login + Direct API</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar - Status & Settings
    with st.sidebar:
        st.markdown("### ⚙️ System Status")
        
        # Session status with details
        session_info = get_session_info()
        if is_session_valid():
            st.success("✅ Session Active")
            st.caption(f"Token: {session_info['token_preview']}")
            st.caption(f"Cookies: {session_info['cookie_count']}")
        else:
            st.warning("⚠️ No Active Session")
        
        # 2Captcha status
        api_key = os.environ.get("CAPTCHA_API_KEY")
        if api_key:
            solver = CaptchaSolver(api_key)
            balance = solver.get_balance()
            st.info(f"💰 2Captcha Balance: ${balance:.2f}")
        else:
            st.error("❌ No CAPTCHA API Key")
        
        # Database status
        if LOCATIONS_DB.exists():
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM villages")
                village_count = cursor.fetchone()[0]
                st.success(f"📊 Database: {village_count:,} villages")
        else:
            st.error("❌ Database not found")
        
        st.divider()
        
        # Manual token input
        st.markdown("### 🔑 Manual Token Entry")
        with st.expander("Paste Token Manually"):
            manual_token = st.text_input("_append Token", type="password")
            if st.button("Save Token"):
                if manual_token:
                    api = KaveriAPI()
                    api.set_token(manual_token)
                    st.success("Token saved!")
                    st.rerun()
    
    # Main content tabs
    tab1, tab2, tab3 = st.tabs(["🔐 Login", "🔍 Search", "📊 Results"])
    
    # ============== TAB 1: LOGIN ==============
    with tab1:
        st.markdown("### Step 1: Browser Login")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("""
            <div class="status-card">
                <h4>📋 Simple Login Steps</h4>
                <ol>
                    <li><strong>Click "Launch Browser"</strong> below</li>
                    <li><strong>Enter your credentials</strong> (username & password)</li>
                    <li><strong>Solve the CAPTCHA</strong></li>
                    <li><strong>Enter OTP</strong> received on your phone</li>
                    <li><strong>Navigate to</strong> "Search by Party Name" page</li>
                    <li><strong>Click "Extract Token"</strong> - we'll get it automatically!</li>
                </ol>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("🚀 Launch Browser", type="primary", use_container_width=True):
                with st.spinner("Launching Chrome..."):
                    driver, temp_dir = launch_login_browser()
                    if driver:
                        st.session_state["driver"] = driver
                        st.session_state["temp_dir"] = temp_dir
                        st.success("✅ Browser launched! Complete login in the browser window.")
                        st.info("👉 After logging in and reaching the search page, click 'Extract Token' below")
        
        with col2:
            st.markdown("""
            <div class="status-card success">
                <h4>✨ Automatic Token Extraction</h4>
                <p>After you login and reach the search page:</p>
                <ol>
                    <li>Make sure you're on <strong>"Search by Party Name"</strong> page</li>
                    <li>Click <strong>"Extract Token"</strong> button</li>
                    <li>We'll automatically capture your session!</li>
                </ol>
                <p><em>No DevTools needed!</em></p>
            </div>
            """, unsafe_allow_html=True)
        
        # Auto-extract token button
        st.markdown("---")
        st.markdown("### 🔑 Extract Session Token")
        
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
            if st.button("🔄 Extract Session Automatically", type="primary", use_container_width=True):
                if "driver" not in st.session_state:
                    st.error("Please launch browser first!")
                else:
                    driver = st.session_state["driver"]
                    with st.spinner("Extracting session from browser..."):
                        try:
                            # Check if on search page
                            current_url = driver.current_url
                            st.info(f"Current page: {current_url}")
                            
                            # Extract full session (token + cookies)
                            session_data = extract_session_from_browser(driver)
                            token = session_data.get("token")
                            cookies = session_data.get("cookies", [])
                            
                            st.info(f"Found {len(cookies)} cookies")
                            
                            if cookies:  # We need cookies even if no token
                                api = KaveriAPI()
                                api.set_token(token or "", cookies)
                                
                                if token:
                                    st.success(f"✅ Token: {token[:8]}...{token[-4:]}")
                                else:
                                    st.warning("⚠️ Token not found, but cookies saved. May still work!")
                                
                                st.success(f"✅ {len(cookies)} cookies saved!")
                                st.balloons()
                                st.info("👉 Go to **Search** tab to start searching!")
                            else:
                                st.error("No session data found. Make sure you're logged in!")
                                st.warning("Try the manual method below.")
                        except Exception as e:
                            st.error(f"Error: {e}")
                            st.warning("Browser may have been closed. Try manual method.")
        
        with col_btn2:
            if st.button("🗑️ Close Browser", use_container_width=True):
                if "driver" in st.session_state:
                    try:
                        st.session_state["driver"].quit()
                    except:
                        pass
                    del st.session_state["driver"]
                    st.success("Browser closed")
        
        # Test session button
        st.markdown("---")
        st.markdown("### 🧪 Test Session")
        
        if st.button("🔍 Test If Session Works", use_container_width=True):
            with st.spinner("Testing session..."):
                api = KaveriAPI()
                success, message = api.test_session()
                
                if success:
                    st.success(f"✅ {message}")
                else:
                    st.error(f"❌ {message}")
                    st.warning("Session is invalid. Please login again.")
        
        # Manual fallback
        st.markdown("---")
        with st.expander("📝 Manual Token Entry (if auto-extract fails)"):
            st.markdown("""
            **If automatic extraction doesn't work:**
            1. In the browser, press **F12** to open DevTools
            2. Go to **Network** tab
            3. Click any dropdown (District, Taluka, etc.)
            4. Click on the API request (GetTalukaAsync, etc.)
            5. Look at **Request Headers**
            6. Find **`_append`** and copy its value
            """)
            
            token_input = st.text_input(
                "Paste the _append token:",
                type="password",
                help="32-character hex string from request headers"
            )
            
            if st.button("💾 Save Manual Token"):
                if token_input and len(token_input) >= 20:
                    api = KaveriAPI()
                    api.set_token(token_input)
                    st.success("✅ Token saved! Go to Search tab.")
                    st.balloons()
                else:
                    st.error("Please enter a valid token (should be ~32 characters)")
    
    # ============== TAB 2: SEARCH ==============
    with tab2:
        if not is_session_valid():
            st.warning("⚠️ Please complete login first (Tab 1)")
            st.stop()
        
        st.markdown("### Step 2: Configure Search")
        
        # Search form
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 👤 Party Details")
            party_name = st.text_input("Party Name *", placeholder="e.g., KRISHNAPPA")
            
            col_from, col_to = st.columns(2)
            with col_from:
                from_date = st.date_input("From Date", value=date(2003, 1, 1))
            with col_to:
                to_date = st.date_input("To Date", value=date.today())
        
        with col2:
            st.markdown("#### 📍 Location")
            
            districts = get_districts()
            district_options = {d["name"]: d["code"] for d in districts}
            selected_district = st.selectbox("District *", ["-- Select --"] + list(district_options.keys()))
            
            district_code = district_options.get(selected_district)
            
            # Taluka dropdown
            if district_code:
                talukas = get_talukas(district_code)
                taluka_options = {"ALL TALUKAS": None}
                taluka_options.update({t["name"]: t["code"] for t in talukas})
                selected_taluka = st.selectbox("Taluka", list(taluka_options.keys()))
                taluk_code = taluka_options.get(selected_taluka)
            else:
                taluk_code = None
                st.selectbox("Taluka", ["-- Select District First --"], disabled=True)
            
            # Hobli dropdown
            if taluk_code:
                hoblis = get_hoblis(taluk_code)
                hobli_options = {"ALL HOBLIS": None}
                hobli_options.update({h["name"]: h["code"] for h in hoblis})
                selected_hobli = st.selectbox("Hobli", list(hobli_options.keys()))
                hobli_code = hobli_options.get(selected_hobli)
            else:
                hobli_code = None
                if district_code and not taluk_code:
                    st.info("Searching all talukas in district")
                else:
                    st.selectbox("Hobli", ["-- Select Taluka First --"], disabled=True)
        
        # Village count preview
        st.markdown("---")
        
        if district_code:
            village_count = count_villages(
                hobli_code=hobli_code,
                taluk_code=taluk_code,
                district_code=district_code
            )
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown(f"""
                <div class="metric-container">
                    <div class="metric-value">{village_count:,}</div>
                    <div class="metric-label">Villages to Search</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                est_time = village_count * 8  # ~8 seconds per village with CAPTCHA
                st.markdown(f"""
                <div class="metric-container">
                    <div class="metric-value">{est_time // 60}m {est_time % 60}s</div>
                    <div class="metric-label">Estimated Time</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                est_cost = village_count * 0.003
                st.markdown(f"""
                <div class="metric-container">
                    <div class="metric-value">${est_cost:.2f}</div>
                    <div class="metric-label">CAPTCHA Cost</div>
                </div>
                """, unsafe_allow_html=True)
        
        # Options
        st.markdown("---")
        
        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            use_browser = st.checkbox(
                "🌐 Use Browser for requests", 
                value=True,
                help="Keep browser open and make requests through it. More reliable but requires browser to stay open."
            )
        with col_opt2:
            if "driver" in st.session_state:
                st.success("✅ Browser connected")
            else:
                if use_browser:
                    st.warning("⚠️ Launch browser in Login tab first")
        
        # Search button
        st.markdown("---")
        
        if st.button("🚀 START SEARCH", type="primary", use_container_width=True, disabled=not (party_name and district_code)):
            if not party_name:
                st.error("Enter party name")
            elif not district_code:
                st.error("Select a district")
            else:
                # Get villages
                villages = get_villages(
                    hobli_code=hobli_code,
                    taluk_code=taluk_code,
                    district_code=district_code
                )
                
                if not villages:
                    st.error("No villages found")
                else:
                    # Initialize
                    driver = st.session_state.get("driver") if use_browser else None
                    api = KaveriAPI(browser_driver=driver)
                    api_key = os.environ.get("CAPTCHA_API_KEY")
                    
                    if not api_key:
                        st.error("No CAPTCHA API key configured")
                        st.stop()
                    
                    solver = CaptchaSolver(api_key)
                    
                    # Output file
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_file = EXPORTS_DIR / f"ec_{party_name}_{timestamp}.csv"
                    
                    # Progress
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results_count = st.empty()
                    
                    all_results = []
                    errors = []
                    
                    # Search loop
                    for idx, village in enumerate(villages):
                        progress = (idx + 1) / len(villages)
                        progress_bar.progress(progress)
                        status_text.markdown(f"**Searching:** {village['name']} ({idx + 1}/{len(villages)})")
                        
                        try:
                            # Generate CAPTCHA
                            captcha_id, captcha_img = api.generate_captcha()
                            
                            # Solve CAPTCHA
                            captcha_code = solver.solve(captcha_img)
                            
                            # Search
                            results = api.search(
                                village_code=village["code"],
                                party_name=party_name,
                                from_date=from_date.strftime("%Y-%m-%d"),
                                to_date=to_date.strftime("%Y-%m-%d"),
                                captcha_id=captcha_id,
                                captcha_code=captcha_code,
                                use_browser=use_browser
                            )
                            
                            # Add metadata
                            for r in results:
                                r["_village_code"] = village["code"]
                                r["_village_name"] = village["name"]
                            
                            all_results.extend(results)
                            
                            # Save incrementally
                            if results:
                                file_exists = output_file.exists()
                                with open(output_file, "a", newline="", encoding="utf-8") as f:
                                    writer = csv.DictWriter(f, fieldnames=results[0].keys())
                                    if not file_exists:
                                        writer.writeheader()
                                    writer.writerows(results)
                            
                            results_count.markdown(f"**Found:** {len(all_results)} records")
                            
                        except Exception as e:
                            errors.append(f"{village['name']}: {e}")
                        
                        # Rate limit
                        time.sleep(1)
                    
                    # Complete
                    progress_bar.progress(1.0)
                    status_text.markdown("**✅ Search Complete!**")
                    
                    # Store results in session
                    st.session_state["search_results"] = all_results
                    st.session_state["output_file"] = str(output_file)
                    st.session_state["errors"] = errors
                    
                    st.success(f"✅ Found {len(all_results)} records! Check Results tab.")
                    st.balloons()
    
    # ============== TAB 3: RESULTS ==============
    with tab3:
        st.markdown("### Search Results")
        
        if "search_results" not in st.session_state:
            st.info("No search results yet. Run a search first.")
        else:
            results = st.session_state["search_results"]
            output_file = st.session_state.get("output_file")
            errors = st.session_state.get("errors", [])
            
            # Stats
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Records", f"{len(results):,}")
            
            with col2:
                st.metric("Output File", Path(output_file).name if output_file else "N/A")
            
            with col3:
                st.metric("Errors", len(errors))
            
            # Download button
            if output_file and Path(output_file).exists():
                with open(output_file, "rb") as f:
                    st.download_button(
                        "📥 Download CSV",
                        data=f.read(),
                        file_name=Path(output_file).name,
                        mime="text/csv",
                        type="primary"
                    )
            
            # Preview
            if results:
                st.markdown("#### Preview (First 100 records)")
                import pandas as pd
                df = pd.DataFrame(results[:100])
                st.dataframe(df, use_container_width=True)
            
            # Errors
            if errors:
                with st.expander(f"⚠️ Errors ({len(errors)})"):
                    for err in errors:
                        st.error(err)
        
        # Recent exports
        st.markdown("---")
        st.markdown("#### 📁 Recent Exports")
        
        exports = sorted(EXPORTS_DIR.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)[:10]
        
        if exports:
            for exp in exports:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.text(exp.name)
                with col2:
                    st.text(f"{exp.stat().st_size / 1024:.1f} KB")
                with col3:
                    with open(exp, "rb") as f:
                        st.download_button("📥", data=f.read(), file_name=exp.name, key=exp.name)
        else:
            st.info("No exports yet")
    
    # Footer
    st.markdown("""
    <div class="footer">
        KAVERI Direct Search Tool • Built with ❤️ • Data sourced from kaveri.karnataka.gov.in
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()

