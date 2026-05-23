import os
import sys
import urllib.request
import json
import zipfile
import io
import re

installed_packages = set()

# Normalize package names for set checks
def normalize_name(name):
    return re.sub(r'[-_.]+', '-', name).lower()

# Check if a package is already installed or standard library
def is_already_installed(pkg_name, target_dir):
    norm = normalize_name(pkg_name)
    if norm in installed_packages:
        return True
    
    if not os.path.exists(target_dir):
        return False
        
    stdlib = {"os", "sys", "json", "urllib", "zipfile", "io", "re", "math", "time", "datetime", "logging", "threading", "random", "shutil", "glob", "pathlib", "uuid", "hashlib", "subprocess"}
    if norm in stdlib:
        return True
        
    for item in os.listdir(target_dir):
        item_norm = item.lower().replace('_', '-')
        if item_norm == norm or item_norm.startswith(norm + "-") or item_norm.startswith(norm + "."):
            installed_packages.add(norm)
            return True
            
    return False

def parse_requirement(req_str):
    req_str = req_str.strip()
    if not req_str:
        return None
        
    if ';' in req_str:
        req_part, marker_part = req_str.split(';', 1)
        if 'extra' in marker_part:
            return None
        if 'sys_platform' in marker_part and 'win32' not in marker_part:
            return None
        if 'python_version <' in marker_part:
            match = re.search(r'[\'"]([0-9.]+)[\'"]', marker_part)
            if match:
                ver = [int(x) for x in match.group(1).split('.')]
                if ver <= [3, 10]:
                    return None
    else:
        req_part = req_str
        
    match = re.match(r'^([a-zA-Z0-9_\-]+)', req_part.strip())
    if match:
        return match.group(1)
    return None

def select_best_wheel(releases):
    eligible = []
    for r in releases:
        filename = r.get("filename", "")
        if not filename.endswith(".whl"):
            continue
            
        # Exclude other platforms
        exclude_tags = ["manylinux", "musllinux", "macosx", "android", "iphoneos", "win32", "arm64", "ppc64", "s390x", "i686"]
        should_exclude = False
        for tag in exclude_tags:
            if tag in filename.lower():
                # Special case: allow 'win_amd64' even if it has 'win' in it
                if tag == "win32" and "win_amd64" in filename.lower():
                    continue
                should_exclude = True
                break
        if should_exclude:
            continue
            
        eligible.append(r)
        
    if not eligible:
        return None, None
        
    # Order of preference:
    # 1. win_amd64 + cp312
    # 2. win_amd64 + abi3
    # 3. win_amd64
    # 4. none-any
    # 5. any remaining
    
    # 1. win_amd64 + cp312
    for r in eligible:
        fn = r.get("filename", "")
        if "win_amd64" in fn and "cp312" in fn:
            return r.get("url"), fn
            
    # 2. win_amd64 + abi3
    for r in eligible:
        fn = r.get("filename", "")
        if "win_amd64" in fn and "abi3" in fn:
            return r.get("url"), fn
            
    # 3. win_amd64
    for r in eligible:
        fn = r.get("filename", "")
        if "win_amd64" in fn:
            return r.get("url"), fn
            
    # 4. none-any
    for r in eligible:
        fn = r.get("filename", "")
        if "none-any" in fn:
            return r.get("url"), fn
            
    # Fallback to the first eligible wheel
    return eligible[0].get("url"), eligible[0].get("filename")

def install_package(package_name, target_dir):
    version = None
    if "==" in package_name:
        package_name, version = package_name.split("==", 1)
        
    pkg_norm = normalize_name(package_name)
    if package_name not in sys.argv and is_already_installed(pkg_norm, target_dir):
        print(f"Package {package_name} is already installed.")
        return True
        
    print(f"\n--- Installing {package_name} (version: {version or 'latest'}) ---")
    url = f"https://pypi.org/pypi/{package_name}/json"
    if version:
        url = f"https://pypi.org/pypi/{package_name}/{version}/json"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"Failed to fetch PyPI metadata for {package_name}: {e}")
        return False
        
    info = data.get("info", {})
    releases = data.get("urls", [])
    requires_dist = info.get("requires_dist", []) or []
    
    if not releases:
        print(f"No releases found for {package_name}")
        return False
        
    best_url, best_filename = select_best_wheel(releases)
                
    if not best_url:
        print(f"Could not find a suitable .whl file for {package_name}")
        return False
        
    print(f"Selected wheel: {best_filename}")
    print(f"Downloading from {best_url}...")
    
    try:
        req = urllib.request.Request(best_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            wheel_data = response.read()
    except Exception as e:
        print(f"Failed to download wheel: {e}")
        return False
        
    print("Extracting wheel to site-packages...")
    try:
        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(wheel_data)) as z:
            z.extractall(target_dir)
        print(f"Successfully extracted {package_name}!")
        installed_packages.add(pkg_norm)
    except Exception as e:
        print(f"Failed to extract wheel: {e}")
        return False

    # Recursively install dependencies
    if requires_dist:
        print(f"Resolving dependencies for {package_name}...")
        for req_str in requires_dist:
            dep_name = parse_requirement(req_str)
            if dep_name:
                install_package(dep_name, target_dir)
                
    return True

if __name__ == "__main__":
    site_packages = os.path.join("venv12", "Lib", "site-packages")
    
    if len(sys.argv) < 2:
        print("Usage: python direct_installer.py [package_name | -r requirements.txt]")
        sys.exit(1)
        
    if sys.argv[1] == "-r" and len(sys.argv) > 2:
        req_file = sys.argv[2]
        if not os.path.exists(req_file):
            print(f"Requirements file {req_file} not found.")
            sys.exit(1)
            
        with open(req_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "==" in line:
                    pkg = line
                else:
                    match = re.match(r'^([a-zA-Z0-9_\-]+)', line)
                    if match:
                        pkg = match.group(1)
                    else:
                        continue
                install_package(pkg, site_packages)
    else:
        pkg = sys.argv[1]
        install_package(pkg, site_packages)
