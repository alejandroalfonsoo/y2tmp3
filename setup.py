"""Receta de py2app para empaquetar yt2mp3 como .app de macOS."""
from setuptools import setup

APP = ["yt2mp3_app.py"]
DATA_FILES = []

OPTIONS = {
    "plist": {
        "CFBundleName":            "yt2mp3",
        "CFBundleDisplayName":     "yt2mp3",
        "CFBundleIdentifier":      "com.alejandro.yt2mp3",
        "CFBundleVersion":         "1.0.0",
        "CFBundleShortVersionString": "1.0",
        "NSHumanReadableCopyright": "© 2026 Alejandro Alfonso",
        "LSMinimumSystemVersion":  "11.0",
        "NSRequiresAquaSystemAppearance": False,
        "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
    },
    "packages": ["yt_dlp", "PyQt6"],
    "includes": ["sip"],
    "excludes": [
        "tkinter", "test", "unittest", "pydoc_data",
        "PyQt6.QtNetworkAuth", "PyQt6.QtMultimedia",
        "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtBluetooth", "PyQt6.QtPositioning",
        "PyQt6.QtSerialPort", "PyQt6.QtTest", "PyQt6.QtSql",
    ],
    "optimize": 2,
    "compressed": True,
    "argv_emulation": False,
}

setup(
    app=APP,
    name="yt2mp3",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
