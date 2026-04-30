import os
import PyQt6
print(f"PyQt6 location: {os.path.dirname(PyQt6.__file__)}")
try:
    from PyQt6 import QtCore
    print("Success!")
except ImportError as e:
    print(f"Failed: {e}")