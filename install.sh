#!/usr/bin/env bash
# Installs an app-menu launcher and a login autostart entry for Lunar Phase, then starts it.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

missing=()
python3 -c 'import gi; gi.require_version("Gtk","3.0")' 2>/dev/null || missing+=(python3-gi gir1.2-gtk-3.0)
python3 - 2>/dev/null <<'PY' || missing+=(gir1.2-ayatanaappindicator3-0.1)
import gi
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
except ValueError:
    gi.require_version("AppIndicator3", "0.1")
PY
python3 -c 'import cairo' 2>/dev/null || missing+=(python3-cairo)
python3 -c 'import numpy, PIL' 2>/dev/null || missing+=(python3-numpy python3-pil)
if ((${#missing[@]})); then
  echo "Missing packages. Install with:"
  echo "  sudo apt install ${missing[*]}"
  exit 1
fi

python3 - "$DIR" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1])
import lunar_tray as lt
apps = os.path.expanduser("~/.local/share/applications")
os.makedirs(apps, exist_ok=True)
with open(os.path.join(apps, "lunar-phase-tray.desktop"), "w") as f:
    f.write(lt.desktop_entry())
os.makedirs(os.path.dirname(lt.AUTOSTART_FILE), exist_ok=True)
with open(lt.AUTOSTART_FILE, "w") as f:
    f.write(lt.desktop_entry(autostart=True))
print("Installed launcher and autostart entry.")
PY

nohup python3 "$DIR/lunar_tray.py" >/dev/null 2>&1 &
echo "Lunar Phase started — look for the moon in the top bar."
