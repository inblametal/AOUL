#!/usr/bin/env python3
"""
Builds standalone Windows AOUL.exe using the official Python 64-bit Windows PE launcher stub.
Packages all Python modules, diagnostics, templates, and offline web assets.
"""

import glob
import os
from pathlib import Path
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
DIST_DIR.mkdir(exist_ok=True)

# Locate t64.exe / w64.exe from pip distlib
stub_path = None
candidates = [
    Path(sys.base_prefix) / "lib" / "python3.13" / "site-packages" / "pip" / "_vendor" / "distlib" / "t64.exe",
    Path(sys.base_prefix) / "lib" / "python3.13" / "site-packages" / "pip" / "_vendor" / "distlib" / "w64.exe",
]

for c in candidates:
    if c.exists():
        stub_path = c
        break

if not stub_path:
    for p in sys.path:
        found = glob.glob(os.path.join(p, "**", "t64.exe"), recursive=True)
        if found:
            stub_path = Path(found[0])
            break

if not stub_path:
    print("❌ Error: Could not locate Windows 64-bit PE stub (t64.exe) in Python environment.")
    sys.exit(1)

print(f"🔨 Using Windows PE 64-bit launcher stub: {stub_path}")

exe_out = DIST_DIR / "AOUL.exe"
temp_zip = DIST_DIR / "aoul_payload.zip"

print("📦 Creating self-contained application zip payload...")
with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    # Write __main__.py
    main_code = """import sys, os
from pathlib import Path

# Add bundle root to sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run

if __name__ == '__main__':
    run.main()
"""
    zf.writestr("__main__.py", main_code)

    # Add run.py
    zf.write(PROJECT_ROOT / "run.py", arcname="run.py")

    # Add requirements.txt and pyproject.toml
    if (PROJECT_ROOT / "requirements.txt").exists():
        zf.write(PROJECT_ROOT / "requirements.txt", arcname="requirements.txt")
    if (PROJECT_ROOT / "pyproject.toml").exists():
        zf.write(PROJECT_ROOT / "pyproject.toml", arcname="pyproject.toml")

    # Add all files in robosage/
    for root, dirs, files in os.walk(PROJECT_ROOT / "robosage"):
        for file in files:
            if file.endswith((".pyc", ".pyo")) or "__pycache__" in root:
                continue
            full_path = Path(root) / file
            rel_path = full_path.relative_to(PROJECT_ROOT)
            zf.write(full_path, arcname=str(rel_path))

    # Add examples/
    for root, dirs, files in os.walk(PROJECT_ROOT / "examples"):
        for file in files:
            full_path = Path(root) / file
            rel_path = full_path.relative_to(PROJECT_ROOT)
            zf.write(full_path, arcname=str(rel_path))

print("⚡ Combining Windows PE stub with payload into AOUL.exe...")
with open(stub_path, "rb") as f_stub, open(temp_zip, "rb") as f_zip, open(exe_out, "wb") as f_out:
    # Write PE stub
    f_out.write(f_stub.read())
    # Write Shebang (t64.exe looks for shebang header)
    f_out.write(b"#!python.exe\n")
    # Append zip archive payload
    f_out.write(f_zip.read())

# Clean temp zip
temp_zip.unlink(missing_ok=True)

# Make executable permissions
os.chmod(exe_out, 0o755)

print(f"✅ Successfully built Windows standalone executable: {exe_out}")
print(f"   Size: {os.path.getsize(exe_out) / 1024:.1f} KB")
