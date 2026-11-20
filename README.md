# Lunar Phase tray app

A top-bar (AppIndicator) app for Linux that shows the current Moon phase as its icon.

**Menu:** phase name, illumination %, waxing/waning, Moon age and % of the cycle,
countdowns to the next full moon, new moon and quarter, distance and apparent size,
and the zodiac sign the Moon is in.

**Details window** (from the menu, or middle-click the icon): a picture of the Moon
as it looks this hour from NASA's SVS *Dial-A-Moon*. Click the picture to open the
full 730×730 image. You also get the lunation progress, phase angle and every
upcoming principal phase with its date and countdown. When you're offline it shows
a simulated rendering instead.

**Settings submenu:** show the percentage next to the icon, southern-hemisphere
(rotated) view, turn NASA downloads on or off, start at login.

## Run

```bash
./lunar_tray.py            # tray app
./lunar_tray.py --details  # also open the details window right away
./lunar_tray.py --print    # print current data to the terminal and exit
python3 moonphase.py 2026-03-03T11:30   # data for any UTC time
./install.sh               # app-menu launcher + autostart, then start it
```

Requires: `python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-ayatanaappindicator3-0.1` (or the older
`gir1.2-appindicator3-0.1`), `python3-cairo`, `python3-numpy`, `python3-pil`. GNOME needs the
AppIndicator extension, which Ubuntu ships by default.

## How it works

- `moonphase.py` is pure-Python astronomy: the Moon's position comes from the main terms of
  the ELP-2000/82 series and the Sun's from Meeus ch. 25. Illumination comes from the phase
  angle. The times of new moon, first quarter, full moon and last quarter are found by
  root-finding on the Sun–Moon elongation, and they agree with published tables to about a minute.
- `moonrender.py` draws the tray icons with cairo, plus the offline fallback picture.
- Icons, downloaded images and the lock file go in `~/.cache/lunar-phase-tray/`. Settings
  are saved in `~/.config/lunar-phase-tray/config.json`.
