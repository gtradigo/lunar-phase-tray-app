# CLAUDE.md

Linux top-bar (AppIndicator) app showing the current Moon phase. Python 3.10+, GTK 3, no pip
dependencies: everything comes from Ubuntu system packages. See README.md for user-facing docs.

## Layout

- `moonphase.py`: pure-Python astronomy. It must not import GTK, so it stays testable from the CLI.
  - `moon_info(t_unix)` returns a `MoonInfo` dataclass. The UI reads only this dataclass.
  - It uses the Moon's position from the main terms of Meeus ch. 47 (ELP-2000/82) and the Sun's
    from Meeus ch. 25. Illumination comes from the phase angle (Meeus ch. 48).
  - `find_phase()` finds phase instants with a Newton iteration on the Sun–Moon elongation.
  - `moon_sky(t_unix, lat, lon)` returns a `MoonSky`: current topocentric altitude and azimuth,
    plus the next rise, set and upper transit within 48 h (`None` when there isn't one, e.g.
    near the poles). It is kept separate from `MoonInfo` because it needs a location.
  - Rise/set uses geocentric altitude against h0 = 0.7275·parallax − 34′ (Meeus ch. 15).
    Transit is where the hour angle crosses 0.
  - Run `python3 moonphase.py [YYYY-MM-DDTHH:MM] [lat lon]` (UTC) to print the data.
- `moonrender.py`: images.
  - `render_icon()` draws the tray icon with cairo: the lit limb is a semicircle and the
    terminator is a half-ellipse with x-radius `r·|cos(elongation)|`.
  - `render_fallback_picture()` draws an offline moon with numpy and PIL, used when the NASA
    image can't be fetched.
- `lunar_tray.py`: the GTK app.
  - `LunarTray` builds the indicator and its menu and refreshes them every `UPDATE_SECONDS`.
  - `DetailsWindow` is the window with the picture and details.
  - `LocationDialog` edits the location. `edit_location()` saves it and sets
    `southern_hemisphere` from the latitude, which the user can still toggle afterwards.
  - It also holds the NASA download, config, the autostart entry and the single-instance lock.
- `assets/logo.png`: README logo (512 px), built by `tools/make_logo.py` from a cached NASA
  image. It is not the app's `icon.png`, which is a cairo-drawn phase icon.
- `install.sh`: checks the apt dependencies, then writes `~/.local/share/applications` and
  `~/.config/autostart` entries and starts the app.

## Conventions and gotchas

- **Elongation convention**: 0° = new, 90° = first quarter, 180° = full, 270° = last
  quarter. `waxing = elongation < 180`. Northern view: a waxing Moon is lit on the right.
  - Southern view: icons are mirrored horizontally and the fallback picture is rotated 180°.
  - Don't also flip the sun vector; flipping both cancels out. That bug already happened once.
- **Icons**: AppIndicator only reloads an icon when its *name* changes.
  - Icons are quantized to 2° of elongation and named `moon-{n|s}-{000..179}`.
  - They are cached in `~/.cache/lunar-phase-tray/`, which is set as the icon theme path.
  - Never overwrite an existing icon file in place under the same name.
- **Menu**: AppIndicator menus are exported over DBus. Custom widgets and large images in
  menu items don't render. Rich content belongs in `DetailsWindow`.
  - Info menu items are deliberately left sensitive, because insensitive items show greyed
    out. Clicking any of them opens the details window.
- **NASA images**: from the SVS Dial-A-Moon API, `https://svs.gsfc.nasa.gov/api/dialamoon/YYYY-MM-DDTHH:MM`
  (UTC).
  - Use the `image` field, or `su_image` for south-up. The API returns `http://` URLs, which
    the code rewrites to https.
  - Images are cached per hour and only the last 6 are kept.
  - The download runs in a daemon thread. UI updates must go through `GLib.idle_add`.
  - The offline fallback is shown first, then replaced by the NASA image when it arrives.
- **Time**: everything is computed in Unix seconds (UTC). TT−UT is a constant `DELTA_T = 69`
  seconds; revisit it if the app is used far from the 2020s.
  - Displayed dates use the system locale via `strftime` (the user's locale is Italian).
  - With a location that has a `tz`, every displayed time goes through
    `mp.format_local(t, fmt, self.tz)`. Pass the tz on any new time label too.
  - Phase instants don't depend on location; only rise/set/transit/alt-az do.
- **Brown lunation number**: the epoch constant is the new moon of 1923-01-17 02:41 UTC
  (`-1481836740`). The new moon of 2026-11-09 is lunation 1285.
- **Single instance**: enforced with `fcntl.flock` on `~/.cache/lunar-phase-tray/instance.lock`.
- **Settings**: `~/.config/lunar-phase-tray/config.json`. To add a setting, add a key to
  `DEFAULT_CONFIG` and a `_check()` call in `_build_menu()`.
- **Location**: stored as `cfg["location"] = {name, lat, lon (east +), tz}`, or `None`.
  - It is entered by hand. The "use my timezone" button reads the reference city of the system
    timezone from `/usr/share/zoneinfo/zone1970.tab`.
  - Don't add an online geocoder: it would send the user's location to a third party.
  - The dialog accepts a comma as the decimal separator (Italian locale).
- **Privacy**: only the NASA API is ever contacted, and no user data goes in the requests.
  Keep it that way.

## Verifying changes

- Astronomy: compare against NASA's API values for the same hour (`phase` = illumination %,
  `age`, `distance`). Expected agreement is about 0.01% illumination, 0.01 day age and
  under 50 km distance.
  - Known check: the full moon / total lunar eclipse of 2026-03-03 is at about 11:33 UTC.
  - Rise/set: compare `python3 moonphase.py 2026-11-20T00:00 51.4769 -0.0005` with USNO
    (`https://aa.usno.navy.mil/api/rstt/oneday?date=2026-11-20&coords=51.4769,-0.0005&tz=0`):
    set 01:59, rise 13:50, transit 20:25 UTC. Test with generic places like this one, never
    with the user's own location.
  - Example: `curl -s https://svs.gsfc.nasa.gov/api/dialamoon/2026-11-20T10:00` gives 78.15%.
    `python3 moonphase.py 2026-11-20T10:00` should match.
- UI:
  - The installed app usually holds the single-instance lock. Test in isolation with
    `XDG_CONFIG_HOME=<scratch>/cfg XDG_CACHE_HOME=<scratch>/cache`. This also leaves the
    user's real config alone.
  - Run `timeout 20 ./lunar_tray.py --details &`.
  - Find the window ID by `WM_NAME "Lunar Phase"` (`xprop -root _NET_CLIENT_LIST`; xdotool
    isn't installed).
  - Capture only that window with `import -window <id> out.png`.
  - Don't screenshot the whole root window, which exposes the user's other apps.
- Don't run `pkill -f lunar_tray.py` from a shell command that itself contains that string,
  because it kills its own shell. Use the bracket trick, `pkill -f "[l]unar_tray"`, and run it
  as its own Bash call: if the command line contains the plain name anywhere (a path, a
  heredoc), the shell still matches and kills itself.

## Environment

Ubuntu 22.04, GNOME on X11, with the Ubuntu AppIndicators extension. `AppIndicator3` is
available; `AyatanaAppIndicator3` is not, and the code tries Ayatana first, then falls back.
Git remote: https://github.com/gtradigo/lunar-phase-tray-app (public), branch `main`.
