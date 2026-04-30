import PyInstaller.__main__
import sys
import time
import os
import platform

# 1. Detect Platform
system = platform.system().lower()  # 'windows', 'darwin' (mac), or 'linux'
sep = os.pathsep  # Automatically picks ';' for Win, ':' for Mac/Linux

# 2. Configure Platform-Specific Icons and Flags
if system == 'darwin':
    icon_file = 'icon.icns'
    platform_args = [
        '--osx-entitlements-file', 'entitlements.plist',
        '--osx-bundle-identifier', 'com.realitylens.app',
        '--collect-all', 'objc',
        '--collect-all', 'AppKit',
        '--collect-all', 'Quartz',
    ]
elif system == 'windows':
    icon_file = 'RealityLens_icon.ico'
    platform_args = []
else:  # Linux
    icon_file = 'icon.png'  # Linux usually doesn't embed icons same way, but good to have
    platform_args = []

shared_assets = [
    '--add-data', f'app/ui{sep}app/ui',
    '--add-data', f'version.txt{sep}.',
    '--add-data', f'assets{sep}assets',
    '--windowed',
    '--clean',
    '--icon', icon_file,
    *platform_args
]

# 3. Execution Logic
def run_build(name, entry_script, extra_args=[]):
    print(f"🚀 Starting build for {name} on {system}...")
    start = time.perf_counter()
    
    PyInstaller.__main__.run([
        entry_script,
        '--name', name,
        '--onefile',
        *extra_args,
        *shared_assets
    ])
    
    end = time.perf_counter()
    duration = end - start
    with open('build_log.txt', 'a') as log_file:
        log_file.write(f"\nBuild for {name} took {duration:.2f} seconds")
    print(f"✅ {name} build complete in {duration:.2f}s")

# Build the Cloud App
run_build('RealityLens', 'app/main.py')

# Optional: Build Standalone (Uncomment to use)
# run_build('RealityLens_Standalone', 'Double_model_ai/main.py', [
#     '--add-data', f'.env{sep}.',
#     '--collect-all', 'google.genai',
#     '--collect-all', 'tavily',
#     '--collect-all', 'groq'
# ])

# 4. Post-Build Instructions
if system == 'darwin':
    print("\n👉 Mac Signing:")
    print("   codesign --force --deep --sign - 'dist/RealityLens.app'")
elif system == 'windows':
    print("\n👉 Windows: Find your .exe in the 'dist' folder.")