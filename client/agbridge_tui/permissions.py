"""
agbridge_tui.permissions — macOS Full Disk Access checks
"""

import os

def has_full_disk_access() -> bool:
    """
    Check if the process has macOS Full Disk Access.
    Attempts to read typically protected directories.
    Returns True if successful or if fallback conditions apply.
    """
    protected_paths = [
        os.path.expanduser("~/Library/Messages"),
        os.path.expanduser("~/Library/Safari"),
        "/Library/Application Support/com.apple.TCC",
    ]
    
    for path in protected_paths:
        if os.path.exists(path):
            try:
                # Attempt to list directory contents to trigger PermissionError if no FDA
                list(os.scandir(path))
                return True
            except PermissionError:
                return False
                
    # If paths don't exist (e.g., CI or non-macOS environment), assume True
    return True
