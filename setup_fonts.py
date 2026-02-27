"""
Font Setup Script — Downloads Carlito fonts for ResumeAI.
Run: python setup_fonts.py
"""
import os
import shutil
import urllib.request
from pathlib import Path

FONTS_DIR = Path(__file__).parent / "fonts"
FONTS_DIR.mkdir(exist_ok=True)

# Try copying from system first (Linux)
SYSTEM_FONTS = {
    "Carlito-Regular.ttf":    "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
    "Carlito-Bold.ttf":       "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf",
    "Carlito-Italic.ttf":     "/usr/share/fonts/truetype/crosextra/Carlito-Italic.ttf",
    "Carlito-BoldItalic.ttf": "/usr/share/fonts/truetype/crosextra/Carlito-BoldItalic.ttf",
}

# GitHub raw URLs for Carlito fonts (Croscore fonts, Apache 2.0)
DOWNLOAD_URLS = {
    "Carlito-Regular.ttf":    "https://github.com/googlefonts/carlito/raw/main/fonts/ttf/Carlito-Regular.ttf",
    "Carlito-Bold.ttf":       "https://github.com/googlefonts/carlito/raw/main/fonts/ttf/Carlito-Bold.ttf",
    "Carlito-Italic.ttf":     "https://github.com/googlefonts/carlito/raw/main/fonts/ttf/Carlito-Italic.ttf",
    "Carlito-BoldItalic.ttf": "https://github.com/googlefonts/carlito/raw/main/fonts/ttf/Carlito-BoldItalic.ttf",
}

for fname, url in DOWNLOAD_URLS.items():
    dest = FONTS_DIR / fname
    if dest.exists():
        print(f"✓ {fname} already exists")
        continue

    # Try system copy first
    sys_path = SYSTEM_FONTS.get(fname, "")
    if sys_path and os.path.exists(sys_path):
        shutil.copy(sys_path, dest)
        print(f"✓ Copied from system: {fname}")
        continue

    # Download from GitHub
    print(f"⬇  Downloading {fname}...")
    try:
        urllib.request.urlretrieve(url, dest)
        print(f"✓ Downloaded: {fname}")
    except Exception as e:
        print(f"✗ Failed to download {fname}: {e}")

print("\nFont setup complete!")
fonts_present = list(FONTS_DIR.glob("*.ttf"))
print(f"Fonts in ./fonts/: {[f.name for f in fonts_present]}")
