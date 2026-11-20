#!/usr/bin/env python3
"""Lunar Phase tray app — shows the current Moon phase in the top bar."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ValueError, ImportError):
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppIndicator
from gi.repository import GdkPixbuf, GLib, Gtk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import moonphase as mp  # noqa: E402
import moonrender  # noqa: E402

APP_ID = "lunar-phase-tray"
CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), APP_ID)
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), APP_ID)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
AUTOSTART_FILE = os.path.join(GLib.get_user_config_dir(), "autostart", f"{APP_ID}.desktop")
UPDATE_SECONDS = 300
NASA_API = "https://svs.gsfc.nasa.gov/api/dialamoon/{}"
USER_AGENT = "lunar-phase-tray/1.0"

DEFAULT_CONFIG = {
    "show_label": False,       # illumination % next to the icon
    "southern_hemisphere": False,
    "use_nasa_images": True,
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# --------------------------------------------------------------------------
# Moon picture provider
# --------------------------------------------------------------------------

def nasa_picture(t_unix: float, south: bool) -> str | None:
    """Download (or reuse cached) NASA SVS Dial-A-Moon image for this hour."""
    hour = datetime.fromtimestamp(t_unix, timezone.utc).strftime("%Y-%m-%dT%H:00")
    tag = hour.replace(":", "").replace("-", "")
    path = os.path.join(CACHE_DIR, f"nasa-{'s' if south else 'n'}-{tag}.jpg")
    if os.path.exists(path):
        return path
    req = urllib.request.Request(NASA_API.format(hour), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        meta = json.load(resp)
    url = meta["su_image" if south else "image"]["url"].replace("http://", "https://", 1)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    # prune old downloads
    for old in sorted(glob.glob(os.path.join(CACHE_DIR, "nasa-*.jpg")))[:-6]:
        try:
            os.remove(old)
        except OSError:
            pass
    return path


def fallback_picture(info: mp.MoonInfo, south: bool) -> str:
    q = int(round(info.elongation)) % 360
    path = os.path.join(CACHE_DIR, f"render-{'s' if south else 'n'}-{q:03d}.jpg")
    if not os.path.exists(path):
        moonrender.render_fallback_picture(path, info.elongation, 730, south)
    return path


# --------------------------------------------------------------------------
# Details window
# --------------------------------------------------------------------------

class DetailsWindow(Gtk.Window):
    IMG_SIZE = 420

    def __init__(self, app: "LunarTray"):
        super().__init__(title="Lunar Phase")
        self.app = app
        self.set_default_size(820, 480)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_from_file(app.current_icon_path)
        self.connect("delete-event", self._on_close)
        self.picture_path: str | None = None

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .moon-bg { background-color: #000000; }
            .phase-title { font-size: 22pt; font-weight: bold; }
            .big-pct { font-size: 34pt; font-weight: 300; }
            .dim { opacity: 0.65; }
            .section { font-weight: bold; margin-top: 10px; }
            .credit { font-size: 8pt; opacity: 0.6; }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add(root)

        # Left: picture on black
        left = Gtk.EventBox()
        left.get_style_context().add_class("moon-bg")
        left.connect("button-press-event", self._open_picture)
        left.set_tooltip_text("Click to open the full-size image")
        lbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        lbox.set_border_width(16)
        self.image = Gtk.Image()
        self.image.set_size_request(self.IMG_SIZE, self.IMG_SIZE)
        self.spinner = Gtk.Spinner()
        overlay = Gtk.Overlay()
        overlay.add(self.image)
        overlay.add_overlay(self.spinner)
        lbox.pack_start(overlay, True, True, 0)
        self.credit = Gtk.Label()
        self.credit.get_style_context().add_class("credit")
        lbox.pack_start(self.credit, False, False, 4)
        left.add(lbox)
        root.pack_start(left, False, False, 0)

        # Right: details
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right.set_border_width(20)
        root.pack_start(right, True, True, 0)

        self.title_lbl = Gtk.Label(xalign=0)
        self.title_lbl.get_style_context().add_class("phase-title")
        right.pack_start(self.title_lbl, False, False, 0)

        pct_row = Gtk.Box(spacing=12)
        self.pct_lbl = Gtk.Label(xalign=0)
        self.pct_lbl.get_style_context().add_class("big-pct")
        self.trend_lbl = Gtk.Label(xalign=0)
        pct_row.pack_start(self.pct_lbl, False, False, 0)
        pct_row.pack_start(self.trend_lbl, False, False, 0)
        right.pack_start(pct_row, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        right.pack_start(self.progress, False, False, 4)

        self.grid = Gtk.Grid(column_spacing=18, row_spacing=4)
        right.pack_start(self.grid, False, False, 6)

        sec = Gtk.Label(label="Upcoming phases", xalign=0)
        sec.get_style_context().add_class("section")
        right.pack_start(sec, False, False, 0)
        self.phase_grid = Gtk.Grid(column_spacing=18, row_spacing=4)
        right.pack_start(self.phase_grid, False, False, 0)

        bottom = Gtk.Box(spacing=6)
        self.updated_lbl = Gtk.Label(xalign=0)
        self.updated_lbl.get_style_context().add_class("dim")
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text("Refresh now")
        refresh.connect("clicked", lambda *_: self.app.refresh(force_picture=True))
        bottom.pack_start(self.updated_lbl, True, True, 0)
        bottom.pack_end(refresh, False, False, 0)
        right.pack_end(bottom, False, False, 0)

    @staticmethod
    def _fill_grid(grid: Gtk.Grid, rows):
        for child in grid.get_children():
            grid.remove(child)
        for i, (k, v) in enumerate(rows):
            kl = Gtk.Label(label=k, xalign=0)
            kl.get_style_context().add_class("dim")
            vl = Gtk.Label(label=v, xalign=0, selectable=True)
            grid.attach(kl, 0, i, 1, 1)
            grid.attach(vl, 1, i, 1, 1)
        grid.show_all()

    def update_info(self, info: mp.MoonInfo):
        now = info.when
        self.title_lbl.set_text(f"{info.emoji}  {info.phase_name}")
        self.pct_lbl.set_text(f"{info.illumination * 100:.1f}%")
        self.trend_lbl.set_markup(
            "<big>▲ Waxing</big>\n<small>illumination increasing</small>" if info.waxing
            else "<big>▼ Waning</big>\n<small>illumination decreasing</small>")
        self.progress.set_fraction(min(1.0, max(0.0, info.lunation_fraction)))
        self.progress.set_text(f"Lunation {info.lunation_number}: {info.lunation_fraction * 100:.0f}% complete")
        self._fill_grid(self.grid, [
            ("Moon age", f"{info.age_days:.2f} days"),
            ("Last new moon", f"{mp.format_local(info.prev_new)}"),
            ("Next full moon", f"{mp.format_local(info.next_full)}  (in {mp.format_countdown(info.next_full - now)})"),
            ("Next new moon", f"{mp.format_local(info.next_new)}  (in {mp.format_countdown(info.next_new - now)})"),
            ("Distance", f"{info.distance_km:,.0f} km"),
            ("Apparent size", f"{info.angular_diameter_arcmin:.1f}′"),
            ("Phase angle", f"{info.phase_angle:.1f}°  (elongation {info.elongation:.1f}°)"),
            ("Moon in", f"{mp.ZODIAC_SYMBOLS[mp.ZODIAC.index(info.zodiac)]} {info.zodiac}  "
                        f"(λ {info.ecliptic_lon:.1f}°, β {info.ecliptic_lat:+.1f}°)"),
        ])
        icons = {"New Moon": "🌑", "First Quarter": "🌓", "Full Moon": "🌕", "Last Quarter": "🌗"}
        self._fill_grid(self.phase_grid, [
            (f"{icons[n]} {n}", f"{mp.format_local(t)}   in {mp.format_countdown(t - now)}")
            for n, t in info.upcoming
        ])
        self.updated_lbl.set_text(f"Updated {datetime.fromtimestamp(now):%H:%M:%S}")
        self.set_icon_from_file(self.app.current_icon_path)

    def set_loading(self, loading: bool):
        if loading:
            self.spinner.start()
            self.spinner.show()
        else:
            self.spinner.stop()
            self.spinner.hide()

    def set_picture(self, path: str, credit: str):
        self.picture_path = path
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, self.IMG_SIZE, self.IMG_SIZE, True)
            self.image.set_from_pixbuf(pb)
        except GLib.Error:
            pass
        self.credit.set_text(credit)

    def _open_picture(self, *_):
        if self.picture_path:
            subprocess.Popen(["xdg-open", self.picture_path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _on_close(self, *_):
        self.hide()
        return True


# --------------------------------------------------------------------------
# Tray indicator
# --------------------------------------------------------------------------

class LunarTray:
    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.cfg = load_config()
        self.info: mp.MoonInfo | None = None
        self.current_icon_path = ""
        self.window: DetailsWindow | None = None
        self._picture_key = None
        self._fetching = False

        self.indicator = AppIndicator.Indicator.new(
            APP_ID, "weather-clear-night", AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_icon_theme_path(CACHE_DIR)
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("Lunar Phase")
        self._build_menu()
        self.refresh()
        GLib.timeout_add_seconds(UPDATE_SECONDS, self._tick)

    # ---- menu -----------------------------------------------------------
    def _item(self, menu, label="", cb=None):
        it = Gtk.MenuItem(label=label)
        it.connect("activate", cb or (lambda *_: self.show_details()))
        menu.append(it)
        return it

    def _build_menu(self):
        m = Gtk.Menu()
        self.mi_title = self._item(m)
        self.mi_illum = self._item(m)
        self.mi_trend = self._item(m)
        self.mi_age = self._item(m)
        m.append(Gtk.SeparatorMenuItem())
        self.mi_full = self._item(m)
        self.mi_new = self._item(m)
        self.mi_quarter = self._item(m)
        m.append(Gtk.SeparatorMenuItem())
        self.mi_dist = self._item(m)
        self.mi_sign = self._item(m)
        m.append(Gtk.SeparatorMenuItem())
        self._item(m, "🔭  Show moon picture & details…")
        m.append(Gtk.SeparatorMenuItem())

        prefs = Gtk.MenuItem(label="Settings")
        sub = Gtk.Menu()
        prefs.set_submenu(sub)
        self.ck_label = self._check(sub, "Show percentage in top bar", "show_label")
        self.ck_south = self._check(sub, "Southern hemisphere view", "southern_hemisphere")
        self.ck_nasa = self._check(sub, "Download NASA moon images", "use_nasa_images")
        self.ck_auto = Gtk.CheckMenuItem(label="Start at login")
        self.ck_auto.set_active(os.path.exists(AUTOSTART_FILE))
        self.ck_auto.connect("toggled", self._toggle_autostart)
        sub.append(self.ck_auto)
        m.append(prefs)
        self._item(m, "Quit", lambda *_: Gtk.main_quit())
        m.show_all()
        self.indicator.set_menu(m)
        # Middle-click on the icon opens the details window
        self.indicator.set_secondary_activate_target(self.mi_title)

    def _check(self, menu, label, key):
        it = Gtk.CheckMenuItem(label=label)
        it.set_active(bool(self.cfg.get(key)))

        def toggled(w):
            self.cfg[key] = w.get_active()
            save_config(self.cfg)
            self.refresh(force_picture=True)
        it.connect("toggled", toggled)
        menu.append(it)
        return it

    def _toggle_autostart(self, w):
        if w.get_active():
            os.makedirs(os.path.dirname(AUTOSTART_FILE), exist_ok=True)
            with open(AUTOSTART_FILE, "w") as f:
                f.write(desktop_entry(autostart=True))
        elif os.path.exists(AUTOSTART_FILE):
            os.remove(AUTOSTART_FILE)

    # ---- updates --------------------------------------------------------
    def _tick(self):
        self.refresh()
        return True

    def refresh(self, force_picture: bool = False):
        info = mp.moon_info()
        self.info = info
        south = self.cfg["southern_hemisphere"]
        now = info.when

        # Icon: quantise to 2 degrees of elongation so the file name changes
        # (AppIndicator only reloads when the icon name changes).
        q = int(round(info.elongation / 2.0)) % 180
        name = f"moon-{'s' if south else 'n'}-{q:03d}"
        path = os.path.join(CACHE_DIR, name + ".png")
        if not os.path.exists(path):
            moonrender.render_icon(path, q * 2.0, 64, south)
        self.current_icon_path = path
        self.indicator.set_icon_full(name, info.phase_name)
        if self.cfg["show_label"]:
            self.indicator.set_label(f"{info.illumination * 100:.0f}%", "100%")
        else:
            self.indicator.set_label("", "")

        # Menu text
        self.mi_title.set_label(f"{info.emoji}  {info.phase_name}")
        self.mi_illum.set_label(f"Illumination: {info.illumination * 100:.1f}%")
        self.mi_trend.set_label("▲ Waxing (growing)" if info.waxing else "▼ Waning (shrinking)")
        self.mi_age.set_label(f"Age: {info.age_days:.1f} days  ·  {info.lunation_fraction * 100:.0f}% of cycle")
        self.mi_full.set_label(f"🌕 Full moon in {mp.format_countdown(info.next_full - now)}  —  "
                               f"{mp.format_local(info.next_full, '%a %d %b, %H:%M')}")
        self.mi_new.set_label(f"🌑 New moon in {mp.format_countdown(info.next_new - now)}  —  "
                              f"{mp.format_local(info.next_new, '%a %d %b, %H:%M')}")
        qn, qt = ("First quarter", info.next_first_quarter) \
            if info.next_first_quarter < info.next_last_quarter else ("Last quarter", info.next_last_quarter)
        qe = "🌓" if qn == "First quarter" else "🌗"
        self.mi_quarter.set_label(f"{qe} {qn} in {mp.format_countdown(qt - now)}  —  "
                                  f"{mp.format_local(qt, '%a %d %b, %H:%M')}")
        self.mi_dist.set_label(f"Distance: {info.distance_km:,.0f} km  ·  {info.angular_diameter_arcmin:.1f}′")
        self.mi_sign.set_label(f"Moon in {mp.ZODIAC_SYMBOLS[mp.ZODIAC.index(info.zodiac)]} {info.zodiac}")

        if self.window:
            self.window.update_info(info)
            self._update_picture(force_picture)

    def _update_picture(self, force: bool = False):
        info = self.info
        south = self.cfg["southern_hemisphere"]
        use_nasa = self.cfg["use_nasa_images"]
        hour = int(info.when // 3600)
        key = (hour, south, use_nasa)
        if (key == self._picture_key and not force) or self._fetching:
            return
        self._picture_key = key

        # Show the offline render instantly, then try to upgrade to NASA's.
        fb = fallback_picture(info, south)
        self.window.set_picture(fb, "Simulated rendering")
        if not use_nasa:
            return
        self._fetching = True
        self.window.set_loading(True)

        def work():
            path, err = None, None
            try:
                path = nasa_picture(info.when, south)
            except Exception as e:  # network errors, API changes, …
                err = e
            GLib.idle_add(done, path, err)

        def done(path, err):
            self._fetching = False
            if self.window:
                self.window.set_loading(False)
                if path:
                    self.window.set_picture(path, "Image: NASA Scientific Visualization Studio")
                else:
                    self.window.set_picture(fb, f"Simulated rendering (NASA image unavailable: {type(err).__name__})")
                    self._picture_key = None
            return False

        threading.Thread(target=work, daemon=True).start()

    def show_details(self):
        if self.window is None:
            self.window = DetailsWindow(self)
            self.window.show_all()
            self.window.set_loading(False)
        self.window.update_info(self.info)
        self._update_picture()
        self.window.present()


def desktop_entry(autostart: bool = False) -> str:
    exe = os.path.abspath(__file__)
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=Lunar Phase",
        "Comment=Current Moon phase in the top bar",
        f"Exec=/usr/bin/env python3 {exe}",
        f"Icon={os.path.join(HERE, 'icon.png')}",
        "Terminal=false",
        "Categories=Utility;Science;Astronomy;",
    ]
    if autostart:
        lines += ["X-GNOME-Autostart-enabled=true", "X-GNOME-Autostart-Delay=5"]
    return "\n".join(lines) + "\n"


def main():
    if "--print" in sys.argv:
        os.execvp(sys.executable, [sys.executable, os.path.join(HERE, "moonphase.py")])
    if not shutil.which("xdg-open"):
        print("warning: xdg-open not found; clicking the picture won't open it", file=sys.stderr)
    import fcntl
    import signal
    os.makedirs(CACHE_DIR, exist_ok=True)
    lock = open(os.path.join(CACHE_DIR, "instance.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Lunar Phase is already running.", file=sys.stderr)
        sys.exit(0)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = LunarTray()
    if "--details" in sys.argv:
        GLib.idle_add(lambda: (app.show_details(), False)[1])
    Gtk.main()


if __name__ == "__main__":
    main()
