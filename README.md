# KAVERI Citizen Assistant

An automation tool for searching property records on the Karnataka Government's KAVERI (Karnataka Valuation and E-Registration) portal.

## Features

- 🔍 **Bulk Property Search** - Search across multiple villages, hoblis, talukas
- 📊 **Export to CSV/Excel** - All results consolidated in one file
- 🖥️ **Web UI** - Easy-to-use Streamlit interface
- 🤖 **Smart Automation** - Auto-fills forms, reuses CAPTCHA
- 📍 **Location Database** - Complete Karnataka location hierarchy (Districts → Talukas → Hoblis → Villages)

## Prerequisites

- **macOS** (tested on macOS Sonoma/Ventura)
- **Python 3.9+** 
- **Google Chrome** browser installed
- **KAVERI Portal Account** (register at [kaveri.karnataka.gov.in](https://kaveri.karnataka.gov.in))

## Installation

### Option 1: Using pip (Recommended)

```bash
# Clone the repository
git clone https://github.com/flipsideview/kaveri.git
cd kaveri

# Create virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Option 2: Using Anaconda

```bash
# Clone the repository
git clone https://github.com/flipsideview/kaveri.git
cd kaveri

# Create conda environment
conda create -n kaveri python=3.11
conda activate kaveri

# Install dependencies
pip install -r requirements.txt
```

### Option 3: Using Homebrew Python

```bash
# Install Python if not already installed
brew install python@3.11

# Clone and setup
git clone https://github.com/flipsideview/kaveri.git
cd kaveri

# Install dependencies
pip3 install -r requirements.txt
```

## Quick Start

### 1. Start the Web UI

```bash
streamlit run citizen_assistant_app.py
```

Open http://localhost:8501 in your browser.

### 2. Build Location Database (First Time Only)

The location database needs to be built once. You can do this via:

**Option A: Web UI**
- Click "🔄 Rebuild Locations" in the sidebar

**Option B: Command Line**
```bash
python kaveri_citizen_assistant.py build-locations
```

This fetches all Districts, Talukas, Hoblis, and Villages from the KAVERI API.

### 3. Run a Search

**Via Web UI:**
1. Enter your KAVERI credentials
2. Enter party name to search
3. Select location (District → Taluka → Hobli → Village)
4. Optionally check "All Villages" to search entire hobli
5. Click "Launch Search"

**Via Command Line:**
```bash
python kaveri_citizen_assistant.py search \
  --username your@email.com \
  --password yourpassword \
  --party "SHIVA" \
  --from-date 2003-01-01 \
  --to-date 2025-12-12 \
  --district 2 \
  --taluka 113 \
  --hobli 499 \
  --all-villages
```

## Search Workflow

1. **Chrome opens** → Tool navigates to KAVERI portal
2. **Manual Login** → You enter credentials, solve CAPTCHA, enter OTP
3. **Navigate** → Go to "Search by Party Name" form
4. **Press ENTER** → Tool takes over
5. **First Search** → You solve CAPTCHA and click SEARCH manually
6. **Remaining Searches** → Tool auto-fills form and searches (CAPTCHA reused)
7. **Results Saved** → CSV + Excel in `exports/` folder

## Project Structure

```
kaveri/
├── kaveri_citizen_assistant.py   # Core automation logic
├── citizen_assistant_app.py      # Streamlit web UI
├── requirements.txt              # Python dependencies
├── kaveri_locations.db          # SQLite database (generated)
├── kaveri_locations.json        # JSON backup (generated)
├── exports/                     # Search results saved here
│   ├── search_results_*.csv
│   └── search_results_*.xlsx
└── har_exports/                 # API analysis data (optional)
```

## CLI Commands

```bash
# Build/refresh location database
python kaveri_citizen_assistant.py build-locations

# Export locations to CSV
python kaveri_citizen_assistant.py export-locations --out locations.csv

# Run search
python kaveri_citizen_assistant.py search \
  --username EMAIL \
  --password PASSWORD \
  --party "NAME" \
  --from-date YYYY-MM-DD \
  --to-date YYYY-MM-DD \
  --district CODE \
  --taluka CODE \
  --hobli CODE \
  --village CODE \
  [--all-taluks] \
  [--all-hoblis] \
  [--all-villages] \
  [--headless]
```

## Troubleshooting

### Chrome crashes immediately
- Ensure Google Chrome is installed and updated
- The tool uses a temporary Chrome profile to avoid conflicts

### "Multiple active session detected" popup
- The tool attempts to handle this automatically
- If it persists, manually click "Yes" to clear sessions
- The tool now properly logs out after each session

### ChromeDriver issues
- ChromeDriver is auto-managed by `webdriver-manager`
- If issues persist, clear cache: `rm -rf ~/.wdm`

### CAPTCHA not being reused
- Make sure you solve the CAPTCHA on the first search
- The tool saves and re-enters the same code for subsequent searches

## Configuration

### Environment Variables (Optional)

```bash
export KAVERI_USERNAME="your@email.com"
export KAVERI_PASSWORD="yourpassword"
```

### Headless Mode

For running without visible browser (not recommended for CAPTCHA):
```bash
python kaveri_citizen_assistant.py search --headless ...
```

## Output Format

Results are saved in `exports/` folder:

| Column | Description |
|--------|-------------|
| district_code | District code |
| district_name | District name |
| taluk_code | Taluka code |
| taluk_name | Taluka name |
| hobli_code | Hobli code |
| hobli_name | Hobli name |
| village_code | Village code |
| village_name | Village name |
| party_name | Search party name |
| from_date | Search from date |
| to_date | Search to date |
| col_1 to col_N | Property record columns |

## License

MIT License - See LICENSE file for details.

## Disclaimer

This tool is for personal use only. Ensure you comply with KAVERI portal's terms of service. The developers are not responsible for any misuse of this tool.

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Support

For issues and feature requests, please use the [GitHub Issues](https://github.com/flipsideview/kaveri/issues) page.

