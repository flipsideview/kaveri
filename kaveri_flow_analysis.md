# KAVERI Portal Flow Analysis Log

**Date:** 2025-12-11  
**URL:** https://kaveri.karnataka.gov.in/ec-search-citizen  
**Purpose:** Document complete login and search flow for automation analysis

---

## 🔍 Network Analysis Results

### Complete API Endpoints Discovered

#### Authentication APIs
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/Generate` | GET | Generate CAPTCHA image |
| `/api/UserLogin` | POST | Login with username, password, captcha |
| `/api/ValidateOTP` | POST | Validate OTP after login |
| `/api/RevokeToken` | POST | Logout / revoke session |

#### Geographic Data APIs
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/GetDistrictAsync` | POST | Get all districts list |
| `/api/GetTalukaAsync` | POST | Get talukas for selected district |
| `/api/GetHobliAsync` | POST | Get hoblis for selected taluka |
| `/api/GetVillageAsync` | POST | Get villages for selected hobli |

#### Search APIs
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/NewECSearch` | POST | **Main EC search endpoint** |
| `/api/GetPropertyTypeMasterAsync` | POST | Get property types |

#### Other APIs
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/getgender` | POST | Get gender options |
| `/api/GetSecurityDatayAsync` | POST | Security data |
| `/api/GetDashboardStatsFY` | GET | Dashboard statistics |
| `/api/GetRevenueGenerated` | GET | Revenue data |
| `/api/GetLiveOffices` | GET | Live office list |
| `/api/GetCitizenDashboard` | GET | Citizen dashboard data |
| `/api/ApplicationStatusDetails` | GET | Application status |
| `/api/GetSROMasterAsync` | POST | SRO master data |
| `/api/GetBhoomiVillage` | POST | Bhoomi village data |

---

## 📊 User Session Flow (from Network Logs)

### Timestamp Sequence
```
1. Page Load
   ├── GET  /api/Generate              → CAPTCHA for login
   ├── POST /api/getgender             → Form options
   ├── POST /api/GetSecurityDatayAsync → Security
   └── GET  /api/GetDashboardStatsFY   → Dashboard

2. Login
   └── POST /api/UserLogin             → Credentials submitted

3. OTP Validation
   └── POST /api/ValidateOTP           → OTP verified

4. EC Search Page Load
   ├── GET  /api/Generate              → New CAPTCHA for search
   ├── POST /api/GetDistrictAsync      → Districts loaded
   ├── POST /api/GetPropertyTypeMasterAsync → Property types
   └── POST /api/GetVillageAsync       → Default villages

5. Location Selection
   ├── POST /api/GetTalukaAsync        → User selected district
   ├── POST /api/GetHobliAsync         → User selected taluka
   └── POST /api/GetVillageAsync       → User selected hobli

6. Search Execution
   └── POST /api/NewECSearch           → Search performed!

7. Logout
   └── POST /api/RevokeToken           → Session ended
```

---

## 🎯 Key Findings

### 1. CAPTCHA Requirement
- CAPTCHA is required for **login** (`/api/UserLogin`)
- CAPTCHA is required for **each search** (`/api/NewECSearch`)
- CAPTCHA is generated via `/api/Generate`

### 2. Search API Structure
The main search happens via:
```
POST /api/NewECSearch
```
This is the key endpoint to understand for automation.

### 3. Geographic Hierarchy
```
District → Taluka → Hobli → Village
```
Each level is fetched via separate API calls when parent is selected.

### 4. Authentication Flow
```
1. Generate CAPTCHA (/api/Generate)
2. Submit Login (/api/UserLogin) with:
   - Username
   - Password
   - CAPTCHA response
3. Validate OTP (/api/ValidateOTP)
4. Access granted
```

---

## 🔧 Automation Strategy

### Option A: Selenium + Manual CAPTCHA
- Use Selenium for form filling
- Pause for manual CAPTCHA solving
- Continue automation after CAPTCHA

### Option B: Direct API Calls
- Make direct API calls to:
  - `/api/GetDistrictAsync` - Get all districts
  - `/api/GetTalukaAsync` - Get all talukas
  - `/api/GetHobliAsync` - Get all hoblis
  - `/api/GetVillageAsync` - Get all villages
- Export complete location hierarchy
- Use for targeted manual searches

### Option C: Hybrid Approach (Recommended)
1. Export location hierarchy via API (no CAPTCHA needed)
2. Use Selenium for actual searches with manual CAPTCHA
3. Download results automatically

---

## 📁 Files Generated

- `kaveri_document_search.ipynb` - Main automation notebook
- `kaveri_flow_analysis.md` - This analysis file

---

## Next Steps

1. [ ] Capture actual API request/response payloads
2. [ ] Test direct API calls for geographic data
3. [ ] Build location hierarchy export tool
4. [ ] Create semi-automated search workflow

---

*Last Updated: 2025-12-11 10:20 UTC*
