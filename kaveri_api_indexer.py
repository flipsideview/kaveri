#!/usr/bin/env python3
"""
KAVERI API Direct Indexer
Downloads complete location hierarchy directly from KAVERI API (103.138.197.99)
This ensures no missing entries compared to web scraping.
"""

import requests
import json
import sqlite3
import time
from pathlib import Path
from datetime import datetime

# API Base URL
BASE_URL = "https://kaveri.karnataka.gov.in/api"

# Headers mimicking browser
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://kaveri.karnataka.gov.in",
    "Referer": "https://kaveri.karnataka.gov.in/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

DB_PATH = Path(__file__).parent / "kaveri_locations.db"
JSON_PATH = Path(__file__).parent / "kaveri_locations_complete.json"


def setup_database():
    """Create SQLite database with proper schema"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Districts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS districts (
            district_code INTEGER PRIMARY KEY,
            district_name_en TEXT,
            district_name_kn TEXT,
            bhoomi_district_code TEXT
        )
    """)
    
    # Talukas table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS talukas (
            taluk_code INTEGER PRIMARY KEY,
            taluk_name_en TEXT,
            taluk_name_kn TEXT,
            district_code INTEGER,
            unit TEXT,
            FOREIGN KEY (district_code) REFERENCES districts(district_code)
        )
    """)
    
    # Hoblis table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hoblis (
            hobli_code INTEGER PRIMARY KEY,
            hobli_name_en TEXT,
            hobli_name_kn TEXT,
            taluk_code INTEGER,
            bhoomi_taluk_code INTEGER,
            bhoomi_district_code INTEGER,
            bhoomi_hobli_code INTEGER,
            FOREIGN KEY (taluk_code) REFERENCES talukas(taluk_code)
        )
    """)
    
    # Villages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS villages (
            village_code INTEGER,
            village_name_en TEXT,
            village_name_kn TEXT,
            hobli_code INTEGER,
            ulb_code INTEGER,
            sro_code INTEGER,
            bhoomi_taluk_code INTEGER,
            bhoomi_district_code INTEGER,
            bhoomi_village_code INTEGER,
            is_urban INTEGER,
            PRIMARY KEY (village_code, hobli_code, ulb_code),
            FOREIGN KEY (hobli_code) REFERENCES hoblis(hobli_code)
        )
    """)
    
    # Metadata table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    conn.commit()
    return conn


def api_call(endpoint: str, payload: dict = None, retries: int = 3) -> list:
    """Make API call with retries"""
    url = f"{BASE_URL}/{endpoint}"
    
    for attempt in range(retries):
        try:
            response = requests.post(
                url,
                headers=HEADERS,
                json=payload or {},
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"  ⚠ Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                print(f"  ❌ Failed after {retries} attempts")
                return []
    return []


def fetch_districts(conn):
    """Fetch all districts"""
    print("\n📍 Fetching Districts...")
    
    data = api_call("GetDistrictAsync", {
        "headers": {"normalizedNames": {}, "lazyUpdate": None, "headers": {}, "lazyInit": None}
    })
    
    if not data:
        print("  ❌ No districts received")
        return []
    
    cursor = conn.cursor()
    districts = []
    
    for d in data:
        if d.get("districtCode", 0) == 0:  # Skip dummy district
            continue
            
        cursor.execute("""
            INSERT OR REPLACE INTO districts 
            (district_code, district_name_en, district_name_kn, bhoomi_district_code)
            VALUES (?, ?, ?, ?)
        """, (
            d["districtCode"],
            d.get("districtNamee", ""),
            d.get("districtNamek", ""),
            d.get("bhoomiDistrictCode", "")
        ))
        
        districts.append({
            "code": d["districtCode"],
            "name": d.get("districtNamee", ""),
            "name_kn": d.get("districtNamek", ""),
            "bhoomi_code": d.get("bhoomiDistrictCode", "")
        })
    
    conn.commit()
    print(f"  ✓ {len(districts)} districts indexed")
    return districts


def fetch_talukas(conn, district_code: int):
    """Fetch talukas for a district"""
    data = api_call("GetTalukaAsync", {"districtCode": str(district_code)})
    
    if not data:
        return []
    
    cursor = conn.cursor()
    talukas = []
    
    for t in data:
        cursor.execute("""
            INSERT OR REPLACE INTO talukas 
            (taluk_code, taluk_name_en, taluk_name_kn, district_code, unit)
            VALUES (?, ?, ?, ?, ?)
        """, (
            t["talukCode"],
            t.get("talukNamee", ""),
            t.get("talukNamek", ""),
            district_code,
            t.get("unit", "")
        ))
        
        talukas.append({
            "code": t["talukCode"],
            "name": t.get("talukNamee", ""),
            "name_kn": t.get("talukNamek", ""),
            "district_code": district_code
        })
    
    conn.commit()
    return talukas


def fetch_hoblis(conn, taluk_code: int):
    """Fetch hoblis for a taluka"""
    data = api_call("GetHobliAsync", {"talukaCode": str(taluk_code)})
    
    if not data:
        return []
    
    cursor = conn.cursor()
    hoblis = []
    
    for h in data:
        cursor.execute("""
            INSERT OR REPLACE INTO hoblis 
            (hobli_code, hobli_name_en, hobli_name_kn, taluk_code, 
             bhoomi_taluk_code, bhoomi_district_code, bhoomi_hobli_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            h["hoblicode"],
            h.get("hoblinamee", ""),
            h.get("hoblinamek", ""),
            taluk_code,
            h.get("bhoomitalukcode", 0),
            h.get("bhoomiDistrictCode", 0),
            h.get("bhoomihoblicode", 0)
        ))
        
        hoblis.append({
            "code": h["hoblicode"],
            "name": h.get("hoblinamee", ""),
            "name_kn": h.get("hoblinamek", ""),
            "taluk_code": taluk_code
        })
    
    conn.commit()
    return hoblis


def fetch_villages(conn, hobli_code: int):
    """Fetch villages for a hobli"""
    data = api_call("GetVillageAsync", {"hobliCode": str(hobli_code)})
    
    if not data:
        return []
    
    cursor = conn.cursor()
    villages = []
    
    for v in data:
        cursor.execute("""
            INSERT OR REPLACE INTO villages 
            (village_code, village_name_en, village_name_kn, hobli_code,
             ulb_code, sro_code, bhoomi_taluk_code, bhoomi_district_code, 
             bhoomi_village_code, is_urban)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            v["villagecode"],
            v.get("villagenamee", ""),
            v.get("villagenamek", ""),
            hobli_code,
            v.get("ulbcode", 0),
            v.get("sroCode", 0),
            v.get("bhoomitalukcode", 0),
            v.get("bhoomiDistrictCode", 0),
            v.get("bhoomivillagecode", 0),
            1 if v.get("isurban", False) else 0
        ))
        
        villages.append({
            "code": v["villagecode"],
            "name": v.get("villagenamee", ""),
            "name_kn": v.get("villagenamek", ""),
            "hobli_code": hobli_code,
            "sro_code": v.get("sroCode", 0),
            "is_urban": v.get("isurban", False)
        })
    
    conn.commit()
    return villages


def index_all(specific_district: int = None):
    """Index all locations from KAVERI API"""
    print("=" * 60)
    print("KAVERI API Direct Indexer")
    print(f"Target: {BASE_URL} (103.138.197.99)")
    print("=" * 60)
    
    conn = setup_database()
    
    # Track stats
    stats = {
        "districts": 0,
        "talukas": 0,
        "hoblis": 0,
        "villages": 0
    }
    
    # Full hierarchy for JSON export
    hierarchy = []
    
    # Fetch districts
    districts = fetch_districts(conn)
    stats["districts"] = len(districts)
    
    # Filter to specific district if requested
    if specific_district:
        districts = [d for d in districts if d["code"] == specific_district]
        print(f"\n🎯 Filtering to district code: {specific_district}")
    
    # For each district, fetch talukas
    for i, district in enumerate(districts):
        print(f"\n📍 [{i+1}/{len(districts)}] {district['name']} (Code: {district['code']})")
        
        district_data = {
            "district_code": district["code"],
            "district_name": district["name"],
            "talukas": []
        }
        
        talukas = fetch_talukas(conn, district["code"])
        stats["talukas"] += len(talukas)
        print(f"  📌 {len(talukas)} talukas")
        
        # For each taluka, fetch hoblis
        for taluka in talukas:
            taluka_data = {
                "taluk_code": taluka["code"],
                "taluk_name": taluka["name"],
                "hoblis": []
            }
            
            hoblis = fetch_hoblis(conn, taluka["code"])
            stats["hoblis"] += len(hoblis)
            
            # For each hobli, fetch villages
            for hobli in hoblis:
                hobli_data = {
                    "hobli_code": hobli["code"],
                    "hobli_name": hobli["name"],
                    "villages": []
                }
                
                villages = fetch_villages(conn, hobli["code"])
                stats["villages"] += len(villages)
                
                hobli_data["villages"] = villages
                taluka_data["hoblis"].append(hobli_data)
                
                # Rate limiting
                time.sleep(0.2)
            
            district_data["talukas"].append(taluka_data)
            print(f"    • {taluka['name']}: {len(hoblis)} hoblis")
        
        hierarchy.append(district_data)
    
    # Save metadata
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)
    """, ("last_updated", datetime.now().isoformat()))
    cursor.execute("""
        INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)
    """, ("stats", json.dumps(stats)))
    conn.commit()
    conn.close()
    
    # Export to JSON
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "last_updated": datetime.now().isoformat(),
            "stats": stats,
            "hierarchy": hierarchy
        }, f, indent=2, ensure_ascii=False)
    
    # Print summary
    print("\n" + "=" * 60)
    print("✅ INDEXING COMPLETE")
    print("=" * 60)
    print(f"📊 Statistics:")
    print(f"   Districts: {stats['districts']}")
    print(f"   Talukas:   {stats['talukas']}")
    print(f"   Hoblis:    {stats['hoblis']}")
    print(f"   Villages:  {stats['villages']}")
    print(f"\n📁 Database: {DB_PATH}")
    print(f"📁 JSON:     {JSON_PATH}")
    
    return stats


def query_locations(district: str = None, taluka: str = None, hobli: str = None):
    """Query indexed locations"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if district:
        cursor.execute("""
            SELECT * FROM districts 
            WHERE district_name_en LIKE ? OR district_code = ?
        """, (f"%{district}%", district if district.isdigit() else -1))
        results = cursor.fetchall()
        print(f"\n📍 Districts matching '{district}':")
        for r in results:
            print(f"   {r['district_code']}: {r['district_name_en']}")
    
    if taluka:
        cursor.execute("""
            SELECT t.*, d.district_name_en 
            FROM talukas t
            JOIN districts d ON t.district_code = d.district_code
            WHERE t.taluk_name_en LIKE ? OR t.taluk_code = ?
        """, (f"%{taluka}%", taluka if taluka.isdigit() else -1))
        results = cursor.fetchall()
        print(f"\n📌 Talukas matching '{taluka}':")
        for r in results:
            print(f"   {r['taluk_code']}: {r['taluk_name_en']} ({r['district_name_en']})")
    
    if hobli:
        cursor.execute("""
            SELECT h.*, t.taluk_name_en, d.district_name_en 
            FROM hoblis h
            JOIN talukas t ON h.taluk_code = t.taluk_code
            JOIN districts d ON t.district_code = d.district_code
            WHERE h.hobli_name_en LIKE ? OR h.hobli_code = ?
        """, (f"%{hobli}%", hobli if hobli.isdigit() else -1))
        results = cursor.fetchall()
        print(f"\n🏘 Hoblis matching '{hobli}':")
        for r in results:
            print(f"   {r['hobli_code']}: {r['hobli_name_en']} ({r['taluk_name_en']}, {r['district_name_en']})")
    
    conn.close()


def show_stats():
    """Show database statistics"""
    if not DB_PATH.exists():
        print("❌ Database not found. Run indexing first.")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n📊 KAVERI Location Database Statistics")
    print("=" * 50)
    
    cursor.execute("SELECT COUNT(*) FROM districts")
    print(f"Districts: {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT COUNT(*) FROM talukas")
    print(f"Talukas:   {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT COUNT(*) FROM hoblis")
    print(f"Hoblis:    {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT COUNT(*) FROM villages")
    print(f"Villages:  {cursor.fetchone()[0]}")
    
    cursor.execute("SELECT value FROM metadata WHERE key='last_updated'")
    row = cursor.fetchone()
    if row:
        print(f"\nLast Updated: {row[0]}")
    
    conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "index":
            # Full index or specific district
            district = int(sys.argv[2]) if len(sys.argv) > 2 else None
            index_all(district)
            
        elif cmd == "stats":
            show_stats()
            
        elif cmd == "query":
            if len(sys.argv) > 2:
                query_locations(district=sys.argv[2])
            else:
                print("Usage: python kaveri_api_indexer.py query <search_term>")
                
        else:
            print(f"Unknown command: {cmd}")
            print("Usage:")
            print("  python kaveri_api_indexer.py index [district_code]  - Index all or specific district")
            print("  python kaveri_api_indexer.py stats                  - Show database stats")
            print("  python kaveri_api_indexer.py query <term>           - Search locations")
    else:
        print("KAVERI API Indexer")
        print("=" * 50)
        print("Usage:")
        print("  python kaveri_api_indexer.py index              - Index ALL locations (takes ~30 mins)")
        print("  python kaveri_api_indexer.py index 11           - Index only Bagalkot district")
        print("  python kaveri_api_indexer.py stats              - Show database statistics")
        print("  python kaveri_api_indexer.py query Bangalore    - Search for locations")

