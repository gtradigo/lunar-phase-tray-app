"""Lunar phase astronomy — pure Python, no dependencies.

Moon position: truncated ELP-2000/82 series from Meeus, "Astronomical
Algorithms" ch. 47 (largest terms; ~10" in longitude).
Sun position: Meeus ch. 25 (~0.01 deg).
Phase instants are found by root-finding on the Sun–Moon elongation, which
gives times accurate to roughly a minute or two.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone

SYNODIC_MONTH = 29.530588853  # days
DELTA_T = 69.0  # seconds, TT - UT (good enough for the 2020s)

# D, M, M', F, sum_l (1e-6 deg), sum_r (1e-3 km)
_LR_TERMS = [
    (0, 0, 1, 0, 6288774, -20905355),
    (2, 0, -1, 0, 1274027, -3699111),
    (2, 0, 0, 0, 658314, -2955968),
    (0, 0, 2, 0, 213618, -569925),
    (0, 1, 0, 0, -185116, 48888),
    (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158),
    (2, -1, -1, 0, 57066, -152138),
    (2, 0, 1, 0, 53322, -170733),
    (2, -1, 0, 0, 45758, -204586),
    (0, 1, -1, 0, -40923, -129620),
    (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755),
    (2, 0, 0, -2, 15327, 10321),
    (0, 0, 1, 2, -12528, 0),
    (0, 0, 1, -2, 10980, 79661),
    (4, 0, -1, 0, 10675, -34782),
    (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636),
    (2, 1, -1, 0, -7888, 24208),
    (2, 1, 0, 0, -6766, 30824),
    (1, 0, -1, 0, -5163, -8379),
    (1, 1, 0, 0, 4987, -16675),
    (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445),
    (4, 0, 0, 0, 3861, -11650),
    (2, 0, -3, 0, 3665, 14403),
    (0, 1, -2, 0, -2689, -7003),
    (2, 0, -1, 2, -2602, 0),
    (2, -1, -2, 0, 2390, 10056),
    (1, 0, 1, 0, -2348, 6322),
    (2, -2, 0, 0, 2236, -9884),
    (0, 1, 2, 0, -2120, 5751),
    (0, 2, 0, 0, -2069, 0),
    (2, -2, -1, 0, 2048, -4950),
    (2, 0, 1, -2, -1773, 4130),
    (2, 0, 0, 2, -1595, 0),
    (4, -1, -1, 0, 1215, -3958),
    (0, 0, 2, 2, -1110, 0),
    (3, 0, -1, 0, -892, 3258),
    (2, 1, 1, 0, -810, 2616),
    (4, -1, -2, 0, 759, -1897),
    (0, 2, -1, 0, -713, -2117),
    (2, 2, -1, 0, -700, 2354),
]

# D, M, M', F, sum_b (1e-6 deg)
_B_TERMS = [
    (0, 0, 0, 1, 5128122),
    (0, 0, 1, 1, 280602),
    (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237),
    (2, 0, -1, 1, 55413),
    (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573),
    (0, 0, 2, 1, 17198),
    (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822),
    (2, -1, 0, -1, 8216),
    (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200),
    (2, 1, 0, -1, -3359),
    (2, -1, -1, 1, 2463),
    (2, -1, 0, 1, 2211),
    (2, -1, -1, -1, 2065),
    (0, 1, -1, -1, -1870),
    (4, 0, -1, -1, 1828),
    (0, 1, 0, 1, -1794),
]

ZODIAC = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]
ZODIAC_SYMBOLS = "♈♉♊♋♌♍♎♏♐♑♒♓"

PHASE_EMOJI = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]
PHASE_NAMES = [
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
]
PRINCIPAL = {0: "New Moon", 90: "First Quarter", 180: "Full Moon", 270: "Last Quarter"}


def _rad(d: float) -> float:
    return d * math.pi / 180.0


def _norm360(d: float) -> float:
    return d % 360.0


def _norm180(d: float) -> float:
    d = (d + 180.0) % 360.0 - 180.0
    return d


def jd_from_unix(t: float) -> float:
    return 2440587.5 + t / 86400.0


def unix_from_jd(jd: float) -> float:
    return (jd - 2440587.5) * 86400.0


def _centuries_tt(t_unix: float) -> float:
    jde = jd_from_unix(t_unix + DELTA_T)
    return (jde - 2451545.0) / 36525.0


def moon_position(t_unix: float):
    """Geocentric ecliptic longitude, latitude (deg) and distance (km)."""
    T = _centuries_tt(t_unix)
    Lp = 218.3164477 + 481267.88123421 * T - 0.0015786 * T**2 + T**3 / 538841 - T**4 / 65194000
    D = 297.8501921 + 445267.1114034 * T - 0.0018819 * T**2 + T**3 / 545868 - T**4 / 113065000
    M = 357.5291092 + 35999.0502909 * T - 0.0001536 * T**2 + T**3 / 24490000
    Mp = 134.9633964 + 477198.8675055 * T + 0.0087414 * T**2 + T**3 / 69699 - T**4 / 14712000
    F = 93.2720950 + 483202.0175233 * T - 0.0036539 * T**2 - T**3 / 3526000 + T**4 / 863310000
    A1 = 119.75 + 131.849 * T
    A2 = 53.09 + 479264.290 * T
    A3 = 313.45 + 481266.484 * T
    E = 1 - 0.002516 * T - 0.0000074 * T**2

    sl = sr = sb = 0.0
    for d, m, mp, f, cl, cr in _LR_TERMS:
        arg = _rad(d * D + m * M + mp * Mp + f * F)
        e = E ** abs(m)
        sl += cl * e * math.sin(arg)
        sr += cr * e * math.cos(arg)
    for d, m, mp, f, cb in _B_TERMS:
        arg = _rad(d * D + m * M + mp * Mp + f * F)
        sb += cb * (E ** abs(m)) * math.sin(arg)

    sl += 3958 * math.sin(_rad(A1)) + 1962 * math.sin(_rad(Lp - F)) + 318 * math.sin(_rad(A2))
    sb += (-2235 * math.sin(_rad(Lp)) + 382 * math.sin(_rad(A3))
           + 175 * math.sin(_rad(A1 - F)) + 175 * math.sin(_rad(A1 + F))
           + 127 * math.sin(_rad(Lp - Mp)) - 115 * math.sin(_rad(Lp + Mp)))

    lon = _norm360(Lp + sl / 1e6)
    lat = sb / 1e6
    dist = 385000.56 + sr / 1000.0
    return lon, lat, dist


def sun_position(t_unix: float):
    """Apparent geocentric ecliptic longitude (deg, without nutation) and distance (km)."""
    T = _centuries_tt(t_unix)
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T**2
    M = 357.52911 + 35999.05029 * T - 0.0001537 * T**2
    e = 0.016708634 - 0.000042037 * T - 0.0000001267 * T**2
    Mr = _rad(M)
    C = ((1.914602 - 0.004817 * T - 0.000014 * T**2) * math.sin(Mr)
         + (0.019993 - 0.000101 * T) * math.sin(2 * Mr)
         + 0.000289 * math.sin(3 * Mr))
    true_lon = L0 + C
    nu = _rad(M + C)
    R_au = 1.000001018 * (1 - e * e) / (1 + e * math.cos(nu))
    omega = 125.04 - 1934.136 * T
    lon = true_lon - 0.00569 - 0.00478 * math.sin(_rad(omega))
    return _norm360(lon), R_au * 149597870.7


def elongation(t_unix: float) -> float:
    """Moon − Sun ecliptic longitude, 0..360 (0 new, 90 first quarter, 180 full)."""
    ml, _, _ = moon_position(t_unix)
    sl, _ = sun_position(t_unix)
    return _norm360(ml - sl)


def find_phase(t_unix: float, target_deg: float, direction: int = 1) -> float:
    """Unix time of the next (direction=+1) or previous (-1) instant at which
    the elongation equals target_deg."""
    cur = elongation(t_unix)
    rate = 360.0 / SYNODIC_MONTH  # deg/day, mean
    if direction > 0:
        delta = (target_deg - cur) % 360.0
        if delta < 1e-6:
            delta = 360.0
    else:
        delta = -((cur - target_deg) % 360.0)
        if delta > -1e-6:
            delta = -360.0
    t = t_unix + delta / rate * 86400.0
    # Newton / secant refinement
    for _ in range(20):
        err = _norm180(elongation(t) - target_deg)
        if abs(err) < 1e-6:
            break
        h = 600.0
        deriv = (_norm180(elongation(t + h) - elongation(t - h))) / (2 * h)  # deg/s
        t -= err / deriv
    return t


@dataclass
class MoonInfo:
    when: float                 # unix time
    elongation: float           # deg 0..360
    phase_angle: float          # deg, Sun-Moon-Earth angle (0 = full)
    illumination: float         # 0..1
    waxing: bool
    phase_index: int            # 0..7 into PHASE_NAMES
    phase_name: str
    emoji: str
    age_days: float             # since previous new moon
    lunation_fraction: float    # 0..1
    distance_km: float
    angular_diameter_arcmin: float
    ecliptic_lon: float
    ecliptic_lat: float
    zodiac: str
    prev_new: float
    next_new: float
    next_first_quarter: float
    next_full: float
    next_last_quarter: float
    lunation_number: int        # Brown lunation number

    @property
    def upcoming(self):
        """Principal phases sorted by time: list of (name, unix_time)."""
        items = [
            ("New Moon", self.next_new),
            ("First Quarter", self.next_first_quarter),
            ("Full Moon", self.next_full),
            ("Last Quarter", self.next_last_quarter),
        ]
        return sorted(items, key=lambda x: x[1])


def _phase_index(elong: float) -> int:
    # Principal phases are given a +/- 1 day window (~12.2 deg);
    # everything in between is a crescent / gibbous.
    w = 360.0 / SYNODIC_MONTH
    for idx, center in ((0, 0.0), (2, 90.0), (4, 180.0), (6, 270.0)):
        if abs(_norm180(elong - center)) <= w:
            return idx
    if elong < 90:
        return 1
    if elong < 180:
        return 3
    if elong < 270:
        return 5
    return 7


def moon_info(t_unix: float | None = None) -> MoonInfo:
    if t_unix is None:
        t_unix = time.time()
    m_lon, m_lat, m_dist = moon_position(t_unix)
    s_lon, s_dist = sun_position(t_unix)
    elong = _norm360(m_lon - s_lon)

    # Geocentric elongation psi and phase angle i (Meeus ch. 48)
    cos_psi = math.cos(_rad(m_lat)) * math.cos(_rad(m_lon - s_lon))
    psi = math.acos(max(-1.0, min(1.0, cos_psi)))
    i = math.atan2(s_dist * math.sin(psi), m_dist - s_dist * math.cos(psi))
    illum = (1 + math.cos(i)) / 2

    idx = _phase_index(elong)
    prev_new = find_phase(t_unix, 0.0, -1)
    nxt = {a: find_phase(t_unix, a, +1) for a in (0.0, 90.0, 180.0, 270.0)}
    age = (t_unix - prev_new) / 86400.0
    # Brown lunation 1 began with the new moon of 1923-01-17 02:41 UTC
    lunation = int(round((prev_new - (-1481836740)) / 86400.0 / SYNODIC_MONTH)) + 1

    return MoonInfo(
        when=t_unix,
        elongation=elong,
        phase_angle=math.degrees(i),
        illumination=illum,
        waxing=elong < 180.0,
        phase_index=idx,
        phase_name=PHASE_NAMES[idx],
        emoji=PHASE_EMOJI[idx],
        age_days=age,
        lunation_fraction=age / ((nxt[0.0] - prev_new) / 86400.0),
        distance_km=m_dist,
        angular_diameter_arcmin=2 * math.degrees(math.asin(1737.4 / m_dist)) * 60,
        ecliptic_lon=m_lon,
        ecliptic_lat=m_lat,
        zodiac=ZODIAC[int(m_lon // 30) % 12],
        prev_new=prev_new,
        next_new=nxt[0.0],
        next_first_quarter=nxt[90.0],
        next_full=nxt[180.0],
        next_last_quarter=nxt[270.0],
        lunation_number=lunation,
    )


def format_countdown(seconds: float) -> str:
    seconds = max(0, int(seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h {m:02d}m"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def format_local(t_unix: float, fmt: str = "%a %d %b %Y, %H:%M", tz=None) -> str:
    """Format a Unix time in `tz` (a tzinfo), or the system local time if None."""
    if tz is None:
        return datetime.fromtimestamp(t_unix).strftime(fmt)
    return datetime.fromtimestamp(t_unix, tz).strftime(fmt)


# --------------------------------------------------------------------------
# Location-dependent quantities: altitude/azimuth, rise, set, transit
# --------------------------------------------------------------------------

EARTH_RADIUS_KM = 6378.14


def moon_equatorial(t_unix: float):
    """Geocentric right ascension, declination (deg) and distance (km)."""
    lon, lat, dist = moon_position(t_unix)
    T = _centuries_tt(t_unix)
    eps = _rad(23.439291 - 0.0130042 * T)
    lam, bet = _rad(lon), _rad(lat)
    ra = math.atan2(math.sin(lam) * math.cos(eps) - math.tan(bet) * math.sin(eps), math.cos(lam))
    dec = math.asin(math.sin(bet) * math.cos(eps) + math.cos(bet) * math.sin(eps) * math.sin(lam))
    return _norm360(math.degrees(ra)), math.degrees(dec), dist


def gmst(t_unix: float) -> float:
    """Greenwich mean sidereal time in degrees (Meeus 12.4)."""
    jd = jd_from_unix(t_unix)
    d = jd - 2451545.0
    T = d / 36525.0
    return _norm360(280.46061837 + 360.98564736629 * d + 0.000387933 * T**2 - T**3 / 38710000)


def _hour_angle_geo_alt(t_unix: float, lat: float, lon: float):
    """(hour angle deg in -180..180, geocentric altitude deg, distance km)."""
    ra, dec, dist = moon_equatorial(t_unix)
    H = _norm180(gmst(t_unix) + lon - ra)
    phi, d, h = _rad(lat), _rad(dec), _rad(H)
    alt = math.asin(math.sin(phi) * math.sin(d) + math.cos(phi) * math.cos(d) * math.cos(h))
    return H, math.degrees(alt), dist


def moon_altaz(t_unix: float, lat: float, lon: float):
    """Topocentric altitude (deg, without refraction) and azimuth (deg from north, eastward)."""
    ra, dec, dist = moon_equatorial(t_unix)
    H = _rad(gmst(t_unix) + lon - ra)
    phi, d = _rad(lat), _rad(dec)
    alt = math.asin(math.sin(phi) * math.sin(d) + math.cos(phi) * math.cos(d) * math.cos(H))
    az = math.atan2(math.sin(H), math.cos(H) * math.sin(phi) - math.tan(d) * math.cos(phi))
    parallax = math.asin(EARTH_RADIUS_KM / dist)
    alt_topo = alt - parallax * math.cos(alt)
    return math.degrees(alt_topo), _norm360(math.degrees(az) + 180.0)


def _rise_set_h0(dist_km: float) -> float:
    """Geocentric altitude of the Moon's centre at apparent rise/set (Meeus ch. 15):
    h0 = 0.7275·π − 34′ (parallax, refraction and semidiameter)."""
    parallax = math.degrees(math.asin(EARTH_RADIUS_KM / dist_km))
    return 0.7275 * parallax - 34.0 / 60.0


def _bisect(f, a: float, b: float, fa: float, tol: float = 1.0) -> float:
    while b - a > tol:
        m = (a + b) / 2
        fm = f(m)
        if (fm > 0) == (fa > 0):
            a, fa = m, fm
        else:
            b = m
    return (a + b) / 2


@dataclass
class MoonSky:
    altitude: float              # deg, topocentric, now
    azimuth: float               # deg from north, now
    above_horizon: bool
    next_rise: float | None      # unix time, None if none in the search window
    next_set: float | None
    next_transit: float | None
    transit_altitude: float | None
    rises: list = None           # all (unix) rises / sets in the window
    sets: list = None


def moon_sky(t_unix: float, lat: float, lon: float, hours: float = 48.0) -> MoonSky:
    """Rise / set / transit times for an observer (lat, lon in degrees, east +)."""
    step = 600.0  # 10 min: the Moon can't rise and set within one step outside polar regions

    def f_alt(t):
        _, alt, dist = _hour_angle_geo_alt(t, lat, lon)
        return alt - _rise_set_h0(dist)

    def f_ha(t):
        return _hour_angle_geo_alt(t, lat, lon)[0]

    rises, sets, transits = [], [], []
    t0 = t_unix
    a_prev, h_prev = f_alt(t0), f_ha(t0)
    end = t_unix + hours * 3600.0
    t = t0
    while t < end:
        t2 = t + step
        a2, h2 = f_alt(t2), f_ha(t2)
        if (a_prev <= 0) != (a2 <= 0):
            ev = _bisect(f_alt, t, t2, a_prev)
            (rises if a_prev <= 0 else sets).append(ev)
        # upper transit: hour angle goes from negative to positive (not the ±180 wrap)
        if h_prev < 0 <= h2 and h2 - h_prev < 90:
            transits.append(_bisect(f_ha, t, t2, h_prev))
        t, a_prev, h_prev = t2, a2, h2

    alt, az = moon_altaz(t_unix, lat, lon)
    tr = transits[0] if transits else None
    return MoonSky(
        altitude=alt,
        azimuth=az,
        above_horizon=f_alt(t_unix) > 0,
        next_rise=rises[0] if rises else None,
        next_set=sets[0] if sets else None,
        next_transit=tr,
        transit_altitude=moon_altaz(tr, lat, lon)[0] if tr else None,
        rises=rises,
        sets=sets,
    )


COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(az: float) -> str:
    return COMPASS[int((az % 360) / 22.5 + 0.5) % 16]


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if args and not args[0].lstrip("-").replace(".", "").isdigit():
        ts = datetime.fromisoformat(args.pop(0)).replace(tzinfo=timezone.utc).timestamp()
    else:
        ts = time.time()
    mi = moon_info(ts)
    print(f"{mi.emoji}  {mi.phase_name}  ({'waxing' if mi.waxing else 'waning'})")
    print(f"Illumination : {mi.illumination * 100:.2f}%")
    print(f"Elongation   : {mi.elongation:.2f} deg")
    print(f"Age          : {mi.age_days:.3f} days ({mi.lunation_fraction * 100:.1f}% of lunation {mi.lunation_number})")
    print(f"Distance     : {mi.distance_km:,.0f} km, diameter {mi.angular_diameter_arcmin:.2f}'")
    print(f"Moon in      : {mi.zodiac} (lon {mi.ecliptic_lon:.2f}, lat {mi.ecliptic_lat:.2f})")
    for name, t in mi.upcoming:
        print(f"{name:14s}: {datetime.fromtimestamp(t, timezone.utc):%Y-%m-%d %H:%M UTC}  (in {format_countdown(t - ts)})")
    if len(args) >= 2:  # optional: <lat> <lon>
        lat, lon = float(args[0]), float(args[1])
        sky = moon_sky(ts, lat, lon)
        utc = lambda t: f"{datetime.fromtimestamp(t, timezone.utc):%Y-%m-%d %H:%M:%S} UTC" if t else "—"  # noqa: E731
        print(f"Observer     : lat {lat:+.4f}, lon {lon:+.4f}")
        print(f"Alt / Az     : {sky.altitude:+.2f} deg / {sky.azimuth:.2f} deg ({compass(sky.azimuth)})")
        print(f"Rises        : {', '.join(utc(t) for t in sky.rises) or '—'}")
        print(f"Sets         : {', '.join(utc(t) for t in sky.sets) or '—'}")
        print(f"Next transit : {utc(sky.next_transit)}  (alt {sky.transit_altitude or 0:.1f} deg)")
