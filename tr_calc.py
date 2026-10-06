"""
tr_calc.py — height-stack calculator for the Longhorn Racing Electric TR jig (Orion).

YOU CHOOSE:   floor clearance  +  loading-beam section height
APP DECIDES:  front hub height, beam centerline height, rear hub height, rear stand height

Height chain (bottom up):
  floor -> required clearance -> (drop as the beam rotates) -> beam bottom / weight bottom
        -> beam height -> beam top -> front fixture (material + hub radius) -> FRONT HUB CENTER
  REAR HUB CENTER = FRONT HUB CENTER (car level at ride height)
  REAR STAND HEIGHT = rear hub center + rear hub radius + material above the hub

The front end, beam and weight rotate as one rigid piece about the front hub axis
(car centerline, front-hub-center height). Internal units are SI; angles in degrees.

This is a geometry/planning calculator. It does NOT certify structural safety.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Constants (all visible here)
# ---------------------------------------------------------------------------
G_STANDARD = 9.80665        # m/s^2, default for the g input
M_PER_IN = 0.0254           # exact
KG_PER_LB = 0.45359237      # exact
N_PER_LBF = KG_PER_LB * G_STANDARD
NM_PER_LBFFT = N_PER_LBF * 0.3048
PA_PER_PSI = N_PER_LBF / M_PER_IN ** 2

# A torsion test is a small-twist test. Beyond this design rotation the inputs are
# almost certainly wrong (e.g. a huge fixture allowance), so the app flags it.
MAX_SENSIBLE_ROTATION_DEG = 10.0

PROV, REQ, SETTING = "provisional", "required", "setting"
PASS, FAIL, NEED = "PASS", "FAIL", "NEEDS INPUT"


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    kind: str
    default: Optional[float]      # SI, or None = you must enter it
    status: str
    group: str
    help: str
    allow_zero: bool = False


INPUTS = [
    # ---- The two numbers you design with ----
    Spec("floor_clear", "Floor clearance at full rotation", "length", None, REQ, "Your choices",
         "How high above the floor you want the lowest point (beam bottom or weight bottom) "
         "to stay, even at the most rotation the test allows. Everything else is sized from "
         "this.", allow_zero=True),
    Spec("beam_h", "Loading-beam section height", "length", None, REQ, "Your choices",
         "Outside height of the beam tube's cross-section (not its length). A taller beam "
         "pushes the front hubs, and so the whole car, higher."),

    # ---- Load & roll ----
    Spec("mass", "Applied mass", "mass", 90.0, PROV, "Load & roll",
         "Mass hung on the lever arm (plates + hanger). Provisional ~90 kg."),
    Spec("lever", "Lever arm L", "length", 0.9144, PROV, "Load & roll",
         "Car centerline to the center of the hanging mass. 3 ft = 914.4 mm."),
    Spec("k_ref", "Expected stiffness K", "stiffness", 1000.0, PROV, "Load & roll",
         "Preliminary chassis torsional rigidity, used only to predict roll."),
    Spec("theta_max", "Maximum allowed roll", "angle", 1.0, PROV, "Load & roll",
         "Largest twist you are willing to put in the car. Clearance is designed for this."),
    Spec("extra_rot", "Extra beam-rotation allowance", "angle", 0.0, PROV, "Load & roll",
         "The beam turns slightly more than the chassis twists (stands, bearings, rod ends "
         "give). Enter the extra rotation at the planned max mass; it scales with load. "
         "0 = chassis twist only.", allow_zero=True),
    Spec("g", "Gravity g", "accel", G_STANDARD, SETTING, "Load & roll",
         "Converts mass to force. 9.80665 m/s² standard."),

    # ---- Hub & fixture sizes ----
    Spec("front_hub_D", "Front hub max diameter", "length", 0.10795, PROV, "Hub & fixture sizes",
         "Largest front-hub diameter where it seats in the front fixture. Defaults to the rear "
         "hub's 4.25 in until the front hub is measured (slide 19 says they differ)."),
    Spec("front_base", "Front fixture material under hub", "length", 0.0127, PROV,
         "Hub & fixture sizes",
         "Fixture material between the beam's top face and the bottom of the front hub. "
         "Front hub center = beam top + this + front hub radius.", allow_zero=True),
    Spec("rear_hub_D", "Rear hub max diameter", "length", 0.10795, PROV, "Hub & fixture sizes",
         "Largest rear-hub diameter. Provisional 4.25 in (107.95 mm)."),
    Spec("rear_top", "Rear stand material above hub", "length", 0.0127, PROV,
         "Hub & fixture sizes",
         "Stand material above the top of the rear hub. Stand height = hub center + hub "
         "radius + this.", allow_zero=True),
    Spec("w_below", "Weight hangs below beam bottom by", "length", 0.0, PROV,
         "Hub & fixture sizes",
         "How far the weight package reaches below the beam's bottom face. 0 if the plates "
         "hang beside the beam and stay above its bottom. A 450 mm plate centered on a "
         "76 mm beam's centerline hangs about 187 mm below it.", allow_zero=True),

    Spec("beam_ext", "Beam end past the weight point", "length", 0.0, PROV,
         "Hub & fixture sizes",
         "How far the beam continues past the center of the hanging weight. When the beam "
         "tilts, its far bottom corner is usually the lowest point, so this matters.",
         allow_zero=True),

    # ---- Beam bending (optional) ----
    Spec("hub_span", "Front hub spacing on the beam", "length", None, REQ,
         "Beam bending (optional)",
         "Lateral distance between the two front fixtures on the beam (about the front "
         "track). Leave blank to treat the beam as rigid."),
    Spec("beam_b", "Beam section width", "length", None, REQ, "Beam bending (optional)",
         "Outside fore-aft width of the beam tube."),
    Spec("beam_t", "Beam wall thickness", "length", None, REQ, "Beam bending (optional)",
         "Tube wall thickness."),
    Spec("E", "Beam modulus E", "modulus", 200e9, SETTING, "Beam bending (optional)",
         "~200 GPa steel, ~69 GPa 6061 aluminum."),
]
SPEC = {s.key: s for s in INPUTS}
BENDING_KEYS = ("hub_span", "beam_b", "beam_h", "beam_t", "E")

# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
METRIC, IMPERIAL = "Metric", "Imperial"
_U = {
    "length": ("mm", 1000.0, "in", 1 / M_PER_IN),
    "mass": ("kg", 1.0, "lb", 1 / KG_PER_LB),
    "force": ("N", 1.0, "lbf", 1 / N_PER_LBF),
    "torque": ("N·m", 1.0, "lbf·ft", 1 / NM_PER_LBFFT),
    "stiffness": ("N·m/deg", 1.0, "lbf·ft/deg", 1 / NM_PER_LBFFT),
    "accel": ("m/s²", 1.0, "ft/s²", 1 / 0.3048),
    "modulus": ("MPa", 1e-6, "ksi", 1 / PA_PER_PSI / 1000),
    "angle": ("deg", 1.0, "deg", 1.0),
    "inertia": ("mm⁴", 1e12, "in⁴", 1 / M_PER_IN ** 4),
    "ratio": ("", 1.0, "", 1.0),
}


def unit(kind, system):
    m, _, i, _ = _U[kind]
    return m if system == METRIC else i


def to_disp(kind, si, system):
    return None if si is None else si * (_U[kind][1] if system == METRIC else _U[kind][3])


def from_disp(kind, x, system):
    return None if x is None else x / (_U[kind][1] if system == METRIC else _U[kind][3])


def fmt(kind, si, system, sig=4):
    x = to_disp(kind, si, system)
    if x is None or not math.isfinite(x):
        return "—"
    s = f"{x:,.1f}" if abs(x) >= 10 ** sig else f"{x:.{sig}g}"
    return f"{s} {unit(kind, system)}".strip()


# ---------------------------------------------------------------------------
# Equations
# ---------------------------------------------------------------------------
def weight_force(m, g=G_STANDARD):
    """F = m·g [N]"""
    return m * g


def torque(F, L):
    """T = F·L [N·m]"""
    return F * L


def roll_deg(T, K):
    """theta = T / K [deg]"""
    return T / K


def low_point_below_pivot(L, depth, theta_deg):
    """Point L out from the rotation axis and 'depth' below it, after rotating theta
    toward its side, sits L·sin(theta) + depth·cos(theta) below the axis."""
    t = math.radians(theta_deg)
    return L * math.sin(t) + depth * math.cos(t)


def rect_tube_I(b, h, t):
    """I = [b·h³ − (b−2t)(h−2t)³]/12 [m⁴]"""
    return (b * h ** 3 - (b - 2 * t) * (h - 2 * t) ** 3) / 12.0


def overhang_tip_slope(F, a, l, E, I):
    """Slope at the load point of the same beam: F·a·(2l + 3a)/(6·E·I) [rad]."""
    return F * a * (2 * l + 3 * a) / (6.0 * E * I)


def overhang_tip_deflection(F, a, l, E, I):
    """Two supports spacing l, load F on overhang a: δ = F·a²·(l + a)/(3·E·I) [m]"""
    return F * a ** 2 * (l + a) / (3.0 * E * I)


@dataclass
class Num:
    label: str
    value: Optional[float]
    kind: str
    why: str
    uses: tuple = ()
    headline: bool = False


@dataclass
class Check:
    label: str
    margin: Optional[float]
    kind: str
    status: str
    why: str
    uses: tuple = ()
    provisional: bool = False


def provisional_in_use(vals, uses):
    for k in uses:
        s = SPEC.get(k)
        if s and s.status == PROV and vals.get(k) is not None and s.default is not None \
                and math.isclose(vals[k], s.default, rel_tol=1e-9, abs_tol=1e-12):
            return True
    return False


def validate(vals):
    bad = {}
    for s in INPUTS:
        x = vals.get(s.key)
        if x is None:
            continue
        if not math.isfinite(x):
            bad[s.key] = "not a number"
        elif x < 0:
            bad[s.key] = "negative"
        elif x == 0 and not s.allow_zero:
            bad[s.key] = "zero is not physically possible"
    b, h, t = vals.get("beam_b"), vals.get("beam_h"), vals.get("beam_t")
    if None not in (b, h, t) and "beam_t" not in bad and 2 * t >= min(b, h):
        bad["beam_t"] = "two walls are thicker than the tube"
    return bad


# ---------------------------------------------------------------------------
# Main calculation
# ---------------------------------------------------------------------------
def compute(vals: dict, system: str = METRIC, test_mass: Optional[float] = None):
    """Return (numbers, checks, bad_inputs, model).

    Design heights are sized for the planned max mass at the roll limit.
    The checks are then evaluated at `test_mass` (the slider); default = planned mass.
    `model` holds functions the app uses to draw the load sweep."""
    v = vals
    bad = validate(v)
    f = lambda kind, x: fmt(kind, x, system)
    have = lambda *ks: all(v.get(k) is not None and k not in bad for k in ks)
    N: dict[str, Num] = {}
    C: list[Check] = []
    model = None

    def need(label, keys, why=""):
        miss = [SPEC[k].label for k in keys if v.get(k) is None]
        brk = [f"{SPEC[k].label} ({bad[k]})" for k in keys if k in bad]
        msg = ("Enter: " + ", ".join(miss) + ". " if miss else "") + \
              ("Fix: " + ", ".join(brk) + ". " if brk else "")
        C.append(Check(label, None, "length", FAIL if brk else NEED, msg + why, keys))

    # ---- 1. Planned load -> torque -> roll -----------------------------------
    F = T = th = None
    if have("mass", "g"):
        F = weight_force(v["mass"], v["g"])
        N["F"] = Num("Weight force F (planned max mass)", F, "force",
                     f"F = m × g = {f('mass', v['mass'])} × {f('accel', v['g'])} = {f('force', F)}.")
    if F is not None and have("lever"):
        T = torque(F, v["lever"])
        N["T"] = Num("Applied torque T (planned max mass)", T, "torque",
                     f"T = F × L = {f('force', F)} × {f('length', v['lever'])} = {f('torque', T)}. "
                     "The weight acts at L from the car centerline, the axis the front turns about.")
    if T is not None and have("k_ref"):
        th = roll_deg(T, v["k_ref"])
        N["theta"] = Num("Predicted roll (planned max mass)", th, "angle",
                         f"θ = T / K = {f('torque', T)} / {f('stiffness', v['k_ref'])} = {th:.4f} deg.")
    ru = ("mass", "g", "lever", "k_ref", "theta_max")
    if th is not None and have("theta_max"):
        ms = v["theta_max"] / th - 1.0
        C.append(Check("MS_roll (planned max mass)", ms, "ratio", PASS if ms >= 0 else FAIL,
                       f"MS = θ_max / θ − 1 = {v['theta_max']:.3f} / {th:.4f} − 1 = {ms:+.2f}. "
                       "Positive = the planned mass keeps roll under your limit.",
                       ru, provisional_in_use(v, ru)))
    else:
        need("MS_roll (planned max mass)", ru)

    # Design state = the heavier of (planned mass) and (mass that reaches the roll limit).
    # Rotation and bending are both evaluated at that one mass, the same way the slider does.
    th_d = m_d = None
    if have("theta_max", "extra_rot", "k_ref", "lever", "g", "mass") and v["mass"] > 0:
        m_lim = v["k_ref"] * v["theta_max"] / (v["g"] * v["lever"])
        m_d = max(v["mass"], m_lim)
        th_d = roll_deg(torque(weight_force(m_d, v["g"]), v["lever"]), v["k_ref"]) \
            + v["extra_rot"] * m_d / v["mass"]
        N["m_lim"] = Num("Mass that reaches the roll limit", m_lim, "mass",
                         f"m = K × θ_max / (g × L) = {f('stiffness', v['k_ref'])} × "
                         f"{v['theta_max']:.3f}° / ({f('accel', v['g'])} × {f('length', v['lever'])}) "
                         f"= {f('mass', m_lim)}.")
        N["theta_d"] = Num("Rotation the heights are designed for", th_d, "angle",
                           f"Design mass = heavier of planned {f('mass', v['mass'])} and roll-limit "
                           f"{f('mass', m_lim)} = {f('mass', m_d)}. Its roll T/K plus the allowance "
                           f"(scaled with load) = {th_d:.4f}°. The heights put the lowest point "
                           "exactly at your clearance in this state, the worst one you allow.")

    if th_d is not None and th_d > MAX_SENSIBLE_ROTATION_DEG:
        C.append(Check("Design rotation is realistic", MAX_SENSIBLE_ROTATION_DEG - th_d, "ratio",
                       FAIL, f"The heights would be sized for {th_d:.1f}°, more than "
                       f"{MAX_SENSIBLE_ROTATION_DEG:g}°. A TR test twists about a degree. Check the "
                       "extra-rotation allowance and the masses.", ("extra_rot", "mass", "theta_max")))

    # ---- 2. Fixture and the points that can hit the floor --------------------
    fix = None
    if have("front_hub_D", "front_base"):
        fix = v["front_base"] + v["front_hub_D"] / 2
        N["fix"] = Num("Front fixture height (beam top → front hub center)", fix, "length",
                       f"= material under hub {f('length', v['front_base'])} + front hub radius "
                       f"{f('length', v['front_hub_D'] / 2)} = {f('length', fix)}.", headline=True)

    pts = None   # (distance out from centerline, depth below front hub axis)
    if fix is not None and have("beam_h", "w_below", "beam_ext", "lever"):
        d_beam = fix + v["beam_h"]
        pts = [(v["lever"] + v["beam_ext"], d_beam),            # far bottom corner of beam
               (v["lever"], d_beam + v["w_below"])]              # bottom of the weight
        N["depth"] = Num("Beam bottom below front hub center", d_beam, "length",
                         f"= fixture {f('length', fix)} + beam height {f('length', v['beam_h'])} = "
                         f"{f('length', d_beam)}. Two points can reach the floor first: the beam's "
                         f"far bottom corner ({f('length', pts[0][0])} out) and the weight bottom "
                         f"({f('length', v['w_below'])} below the beam at L).")

    def lowest(theta_deg, F_n=0.0):
        """Deepest point below the front hub axis after rotating theta, plus beam bending
        under force F_n. Bending at a point past the weight = sag + slope x extra length."""
        def bend(y):
            return F_n * (bend_per_N + slope_per_N * max(0.0, y - v["lever"]))
        return max(low_point_below_pivot(y, d, theta_deg) + bend(y) for y, d in pts)

    # ---- 3. Bending per newton (optional) -------------------------------------
    bend_per_N = 0.0            # sag at the weight point per newton
    slope_per_N = 0.0           # beam slope at the weight point per newton
    if have(*BENDING_KEYS, "lever"):
        l, L = v["hub_span"], v["lever"]
        a = L - l / 2
        if a > 0:
            I = rect_tube_I(v["beam_b"], v["beam_h"], v["beam_t"])
            bend_per_N = overhang_tip_deflection(1.0, a, l, v["E"], I)
            slope_per_N = overhang_tip_slope(1.0, a, l, v["E"], I)
            N["bend"] = Num("Beam bending sag per kg", bend_per_N * (v["g"] or G_STANDARD),
                            "length",
                            f"δ = F·a²·(l + a)/(3·E·I), a = L − l/2 = {f('length', a)}, l = "
                            f"{f('length', l)}, I = {f('inertia', I)}. Past the weight the beam also tilts by "
                            f"F·a·(2l + 3a)/(6·E·I), so its far end sags a bit more. Scales with load.")
        else:
            C.append(Check("Beam bending", None, "length", FAIL,
                           f"Overhang a = L − spacing/2 = {f('length', a)} ≤ 0: the weight is "
                           "between the hubs, so this formula does not apply.", BENDING_KEYS))
    else:
        N["bend"] = Num("Beam bending sag", None, "length",
                        "Not included. Beam treated as rigid. Fill in the optional bending inputs.")

    # ---- 4. Design heights ------------------------------------------------------
    core = ("floor_clear", "beam_h", "front_hub_D", "front_base", "w_below", "beam_ext",
            "lever", "theta_max", "extra_rot", "mass", "g")
    hub = None
    if pts and th_d is not None and have("floor_clear", "mass", "g"):
        below_d = lowest(th_d, weight_force(m_d, v["g"]))
        hub = v["floor_clear"] + below_d
        N["front_hub"] = Num("Front hub-center height", hub, "length",
                             f"= clearance {f('length', v['floor_clear'])} + lowest point below the "
                             f"hub at {th_d:.3f}° {f('length', below_d)} = {f('length', hub)}. The "
                             "lowest the front hubs can sit and still keep your clearance.",
                             headline=True)
        N["x"] = Num("x — rear hub center above floor", hub, "length",
                     f"x = front hub height = {f('length', hub)}. The rear stand sits on the floor "
                     "and holds up the back of the car. Its hub center must match the front so "
                     "the car is level.", headline=True)
        bcl = hub - fix - v["beam_h"] / 2
        N["beam_cl"] = Num("Loading-beam centerline height", bcl, "length",
                           f"= front hub {f('length', hub)} − fixture {f('length', fix)} − half beam "
                           f"{f('length', v['beam_h'] / 2)} = {f('length', bcl)}.", headline=True)
        if have("rear_hub_D", "rear_top"):
            y = hub + v["rear_hub_D"] / 2 + v["rear_top"]
            N["y"] = Num("y — rear stand total height", y, "length",
                         f"y = x + rear hub radius + material above = {f('length', hub)} + "
                         f"{f('length', v['rear_hub_D'] / 2)} + {f('length', v['rear_top'])} = "
                         f"{f('length', y)}.", headline=True)
            gap = hub - v["rear_hub_D"] / 2
            uses = core + ("rear_hub_D",)
            C.append(Check("Room under rear hub", gap, "length", PASS if gap > 0 else FAIL,
                           f"x − hub radius = {f('length', hub)} − {f('length', v['rear_hub_D'] / 2)} "
                           f"= {f('length', gap)}. Space below the hub for the stand's base.",
                           uses, provisional_in_use(v, uses)))
        N["static"] = Num("Lowest point before load", hub - lowest(0.0), "length",
                          f"= front hub {f('length', hub)} − {f('length', lowest(0.0))} = "
                          f"{f('length', hub - lowest(0.0))}. What a ruler reads before any weight.")
    else:
        need("Clearance at this load", core, "These set every height.")
        return N, C, bad, None

    # ---- 5. State at the test mass (slider) -------------------------------------
    if not have("k_ref", "lever", "g"):
        need("Clearance at this load", ("k_ref",), "Needed to turn load into rotation.")
        return N, C, bad, None
    m_plan = v["mass"]

    def theta_at(m):
        """Rotation at mass m: chassis roll T/K plus the allowance scaled with load."""
        chassis = roll_deg(torque(weight_force(m, v["g"]), v["lever"]), v["k_ref"])
        extra = v["extra_rot"] * (m / m_plan) if m_plan > 0 else 0.0
        return chassis + extra

    def low_height(m):
        """Height of the lowest point above the floor at mass m."""
        return hub - lowest(theta_at(m), weight_force(m, v["g"]))

    def mass_where(target):
        """Smallest mass where the lowest point falls to `target` height (bisection)."""
        if low_height(0.0) <= target:
            return 0.0
        hi = max(m_plan, 1.0)
        while low_height(hi) > target:
            if hi > 1e7 or theta_at(hi) > 85:      # never reaches it before ~vertical
                return None
            hi *= 2
        lo = 0.0
        for _ in range(80):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if low_height(mid) > target else (lo, mid)
        return hi

    m = m_plan if test_mass is None else test_mass
    th_m = theta_at(m)
    h_m = low_height(m)
    m_clear = mass_where(v["floor_clear"])
    m_floor = mass_where(0.0)
    T_m = torque(weight_force(m, v["g"]), v["lever"])
    N["m_clear"] = Num("Mass that reaches your clearance", m_clear, "mass",
                       f"Found by stepping the load up until the lowest point falls to "
                       f"{f('length', v['floor_clear'])}. Keep the test below this.")
    N["m_floor"] = Num("Mass that touches the floor", m_floor, "mass",
                       "Past this the floor carries load instead of the car, and every reading is "
                       "wrong.")

    uses = core + ("k_ref",)
    prov = provisional_in_use(v, uses)
    head = (f"At {f('mass', m)}: T = {f('torque', T_m)}, roll = T/K + allowance = "
            f"{th_m:.4f}°, lowest point drops to {f('length', h_m)}. ")
    if m_clear:
        ms = m_clear / m - 1 if m > 0 else float("inf")
        C.append(Check("MS_clearance (mass)", ms if m > 0 else None, "ratio",
                       PASS if m <= m_clear else FAIL,
                       head + f"MS = mass at clearance / applied mass − 1 = {f('mass', m_clear)} / "
                       f"{f('mass', m)} − 1" + (f" = {ms:+.2f}." if m > 0 else "."),
                       uses, prov))
    C.append(Check("Clearance at this load", h_m - v["floor_clear"], "length",
                   PASS if h_m >= v["floor_clear"] else FAIL,
                   f"Lowest point {f('length', h_m)} − required {f('length', v['floor_clear'])} = "
                   f"{f('length', h_m - v['floor_clear'])}.", uses, prov))
    C.append(Check("Above the floor at this load", h_m, "length",
                   PASS if h_m > 0 else FAIL,
                   f"Lowest point height = {f('length', h_m)}. Zero or below means the beam or "
                   "weight is resting on the floor.", uses, prov))

    model = dict(theta_at=theta_at, low_height=low_height, hub=hub, fix=fix,
                 m_clear=m_clear, m_floor=m_floor, pts=pts, bend_per_N=bend_per_N,
                 slope_per_N=slope_per_N, m_design=m_d)
    return N, C, bad, model
