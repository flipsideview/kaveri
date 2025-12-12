"""
KAVERI Citizen Assistant Web UI (Streamlit)
- Uses subprocess to launch Chrome, completely isolated from Streamlit
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from kaveri_citizen_assistant import (
    build_location_hierarchy,
    export_locations_csv,
    LocationRepo,
    SearchConfig,
    build_location_combinations,
    EXPORTS_DIR,
    DB_PATH,
)


def get_repo():
    """Get a fresh LocationRepo instance."""
    if not DB_PATH.exists():
        return None
    return LocationRepo()


def check_db_exists():
    """Check if the location database exists."""
    return DB_PATH.exists()


def run_search_subprocess(username, password, party_name, from_date, to_date,
                          district_code, taluk_code, hobli_code, village_code,
                          all_taluks, all_hoblis, all_villages, property_type_id):
    """Run search in a completely separate subprocess."""
    
    # Build command
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "kaveri_citizen_assistant.py"),
        "search",
        "--username", username,
        "--password", password,
        "--party", party_name,
        "--from-date", from_date,
        "--to-date", to_date,
    ]
    
    if district_code:
        cmd.extend(["--district", str(district_code)])
    if taluk_code:
        cmd.extend(["--taluka", str(taluk_code)])
    if hobli_code:
        cmd.extend(["--hobli", str(hobli_code)])
    if village_code:
        cmd.extend(["--village", str(village_code)])
    if all_taluks:
        cmd.append("--all-taluks")
    if all_hoblis:
        cmd.append("--all-hoblis")
    if all_villages:
        cmd.append("--all-villages")
    if property_type_id:
        cmd.extend(["--property-type", str(property_type_id)])
    
    return cmd


def main():
    st.set_page_config(
        page_title="KAVERI Citizen Assistant",
        page_icon="🏛️",
        layout="wide"
    )
    
    st.title("🏛️ KAVERI Citizen Assistant")
    st.caption("Search Encumbrance Certificate records by Party Name across Karnataka")
    
    # Sidebar - Data Management
    st.sidebar.header("📊 Data Management")
    
    db_exists = check_db_exists()
    
    if db_exists:
        st.sidebar.success("✅ Location database loaded")
    else:
        st.sidebar.warning("⚠️ Location database not found")
    
    col1, col2 = st.sidebar.columns(2)
    
    with col1:
        if st.button("🔄 Rebuild DB"):
            with st.spinner("Fetching locations..."):
                try:
                    build_location_hierarchy()
                    st.success("✅ Done!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Failed: {e}")
    
    with col2:
        if db_exists:
            if st.button("📥 Export CSV"):
                try:
                    export_locations_csv(Path("locations.csv"))
                    st.success("✅ Exported!")
                except Exception as e:
                    st.error(f"❌ Failed: {e}")
    
    # Check if database exists
    if not db_exists:
        st.warning("⚠️ Click 'Rebuild DB' in sidebar first")
        st.stop()
    
    # Load repository
    repo = get_repo()
    if repo is None:
        st.error("Failed to load database")
        st.stop()
    
    # Two columns layout
    left_col, right_col = st.columns([1, 1])
    
    with left_col:
        st.subheader("🔐 Credentials")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        
        st.subheader("🔍 Search")
        party_name = st.text_input("Party Name", placeholder="e.g., SHIVA")
        
        d1, d2 = st.columns(2)
        with d1:
            from_date = st.date_input("From", value=datetime(2003, 1, 1))
        with d2:
            to_date = st.date_input("To", value=datetime.now())
    
    with right_col:
        st.subheader("📍 Location")
        
        # District
        districts = repo.districts()
        dist_opts = {f"{d[0]} - {d[1]}": d[0] for d in districts}
        dist_choice = st.selectbox("District", ["ALL"] + list(dist_opts.keys()))
        district_code = dist_opts.get(dist_choice) if dist_choice != "ALL" else None
        
        # Taluka
        taluk_code = None
        taluka_choice = "ALL"
        if district_code:
            talukas = repo.talukas(district_code)
            taluk_opts = {f"{t[0]} - {t[1]}": t[0] for t in talukas}
            taluka_choice = st.selectbox("Taluka", ["ALL"] + list(taluk_opts.keys()))
            taluk_code = taluk_opts.get(taluka_choice) if taluka_choice != "ALL" else None
        else:
            st.selectbox("Taluka", ["Select District"], disabled=True)
        
        # Hobli
        hobli_code = None
        hobli_choice = "ALL"
        if taluk_code:
            hoblis = repo.hoblis(taluk_code)
            hobli_opts = {f"{h[0]} - {h[1]}": h[0] for h in hoblis}
            hobli_choice = st.selectbox("Hobli", ["ALL"] + list(hobli_opts.keys()))
            hobli_code = hobli_opts.get(hobli_choice) if hobli_choice != "ALL" else None
        else:
            st.selectbox("Hobli", ["Select Taluka"], disabled=True)
        
        # Village
        village_code = None
        village_choice = "ALL"
        if hobli_code:
            villages = repo.villages(hobli_code)
            village_opts = {f"{v[0]} - {v[1]}": v[0] for v in villages}
            village_choice = st.selectbox("Village", ["ALL"] + list(village_opts.keys()))
            village_code = village_opts.get(village_choice) if village_choice != "ALL" else None
        else:
            st.selectbox("Village", ["Select Hobli"], disabled=True)
        
        # Property type
        property_type_id = None
        prop_types = repo.property_types()
        if prop_types:
            pt_opts = {f"{p[0]} - {p[1]}": p[0] for p in prop_types}
            pt_choice = st.selectbox("Property Type", ["None"] + list(pt_opts.keys()))
            property_type_id = pt_opts.get(pt_choice) if pt_choice != "None" else None
    
    st.divider()
    
    # Calculate combinations
    if district_code:
        try:
            temp_cfg = SearchConfig(
                username="x", password="x", party_name="x",
                district_code=district_code,
                taluk_code=taluk_code,
                hobli_code=hobli_code,
                village_code=village_code,
                all_taluks=(taluka_choice == "ALL"),
                all_hoblis=(hobli_choice == "ALL"),
                all_villages=(village_choice == "ALL"),
            )
            combos = build_location_combinations(repo, temp_cfg)
            st.info(f"📊 Will search **{len(combos)}** location(s)")
        except:
            pass
    
    # Launch button
    if st.button("🚀 Launch Search", type="primary", use_container_width=True):
        if not username or not password or not party_name:
            st.error("❌ Username, password, and party name required")
        elif not district_code:
            st.error("❌ Select a district")
        else:
            # Build the command
            cmd = run_search_subprocess(
                username, password, party_name,
                from_date.strftime("%Y-%m-%d"),
                to_date.strftime("%Y-%m-%d"),
                district_code, taluk_code, hobli_code, village_code,
                taluka_choice == "ALL" and district_code,
                hobli_choice == "ALL" and taluk_code,
                village_choice == "ALL" and hobli_code,
                property_type_id
            )
            
            st.success("✅ Launching Chrome in separate process...")
            st.code(" ".join(cmd), language="bash")
            
            st.warning("""
            ### 📋 Instructions
            1. **Chrome will open** in a separate window
            2. **Log in manually** (username, password, CAPTCHA, OTP)
            3. **Navigate to** 'Search by Party Name'
            4. **Press ENTER** in terminal when prompted for CAPTCHA
            5. **Results** will be saved to `exports/` folder
            """)
            
            # Launch in subprocess with visible terminal
            try:
                import platform
                if platform.system() == "Darwin":  # macOS
                    # Open in new Terminal window so user can see prompts
                    # Terminal will close automatically when script completes
                    script_dir = str(Path(__file__).parent.resolve())  # Get absolute path
                    script = " ".join(f'"{c}"' if " " in c else c for c in cmd)
                    apple_script = f'''
                    tell application "Terminal"
                        activate
                        do script "cd {script_dir} && {script}; echo ''; echo 'Press any key to close...'; read -n 1; exit"
                    end tell
                    '''
                    subprocess.Popen(["osascript", "-e", apple_script])
                    st.success("✅ Chrome launched in new Terminal window!")
                    st.info("👉 Check the **Terminal window** for prompts and progress")
                    st.info("💡 Terminal will close automatically after completion")
                else:
                    # Fallback for other OS
                    subprocess.Popen(cmd, cwd=str(Path(__file__).parent))
                    st.success("✅ Process started")
                
            except Exception as e:
                st.error(f"❌ Failed to launch: {e}")
    
    st.divider()
    
    # Show recent exports
    st.subheader("📁 Recent Exports")
    exports = list(EXPORTS_DIR.glob("*.csv"))
    if exports:
        exports.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for f in exports[:5]:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.text(f.name)
            with col2:
                with open(f, "rb") as file:
                    st.download_button("Download", file, f.name, "text/csv", key=f.name)
    else:
        st.info("No exports yet")
    
    repo.close()


if __name__ == "__main__":
    main()
