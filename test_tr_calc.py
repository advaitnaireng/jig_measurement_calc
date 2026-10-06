"""Formula validation for tr_calc.py. Run: python -m unittest test_tr_calc.py
Expected values are worked by hand in the comments."""
import math
import unittest

import tr_calc as tc


def base(**kw):
    v = {s.key: s.default for s in tc.INPUTS}
    v.update(floor_clear=0.0254, beam_h=0.0762)   # 1 in clearance, 3 in beam (test numbers)
    v.update(kw)
    return v


class Formulas(unittest.TestCase):
    def test_torque_807(self):
        # 90 x 9.80665 = 882.60 N ; x 0.9144 = 807.05 N·m
        self.assertAlmostEqual(tc.torque(tc.weight_force(90), 0.9144), 807.05, delta=0.05)

    def test_roll_0807(self):
        self.assertAlmostEqual(tc.roll_deg(807.0, 1000.0), 0.807, places=6)

    def test_overhang(self):
        # 1000*0.09*0.9/(3*200e9*1e-6) = 1.35e-4 m
        self.assertAlmostEqual(tc.overhang_tip_deflection(1000, .3, .6, 200e9, 1e-6), 1.35e-4)

    def test_units(self):
        self.assertAlmostEqual(tc.to_disp("length", 0.2286, tc.IMPERIAL), 9.0)
        self.assertAlmostEqual(tc.from_disp("mass", tc.to_disp("mass", 90, tc.IMPERIAL),
                                            tc.IMPERIAL), 90)


class HeightStack(unittest.TestCase):
    def test_hand_calc(self):
        # fixture = 12.7 + 107.95/2 = 66.675 mm
        # depth = 66.675 + 76.2 + 0 = 142.875 mm
        # theta_d = max(1.0, 0.807) = 1.0 deg
        # below = 914.4 sin1 + 142.875 cos1 = 15.95848 + 142.85324 = 158.81172 mm
        # front hub = 25.4 + 158.81172 = 184.21172 mm = rear hub
        # beam CL = 184.21172 - 66.675 - 38.1 = 79.43672 mm
        # stand = 184.21172 + 53.975 + 12.7 = 250.88672 mm
        # before-load clearance = 184.21172 - 142.875 = 41.33672 mm
        N, C, bad, _ = tc.compute(base())
        self.assertFalse(bad)
        self.assertAlmostEqual(N["fix"].value * 1000, 66.675, places=6)
        self.assertAlmostEqual(N["front_hub"].value * 1000, 184.21172, places=4)
        self.assertAlmostEqual(N["x"].value, N["front_hub"].value)
        self.assertAlmostEqual(N["beam_cl"].value * 1000, 79.43672, places=4)
        self.assertAlmostEqual(N["y"].value * 1000, 250.88672, places=4)
        self.assertAlmostEqual(N["static"].value * 1000, 41.33672, places=4)

    def test_taller_beam_raises_everything_by_same_amount(self):
        a, _, _, _ = tc.compute(base(beam_h=0.0762))
        b, _, _, _ = tc.compute(base(beam_h=0.1016))   # +25.4 mm
        dh = (b["front_hub"].value - a["front_hub"].value) * 1000
        self.assertAlmostEqual(dh, 25.4 * math.cos(math.radians(1.0)), places=6)

    def test_bending_raises_hubs(self):
        rigid = tc.compute(base())[0]["front_hub"].value
        N, _, _, _ = tc.compute(base(hub_span=1.2, beam_b=0.0508, beam_t=0.003175))
        # design mass = roll-limit mass 111.52 kg (> 90 kg planned); beam_ext = 0 so no slope term
        m_d = 1000 * 1.0 / (9.80665 * 0.9144)
        sag = N["bend"].value * m_d
        # rotation also stays 1 deg, so only the sag changes the hub height
        self.assertAlmostEqual(N["front_hub"].value - rigid, sag, places=12)

    def test_bending_keeps_clearance_mass_at_design_mass(self):
        N, C, _, mdl = tc.compute(base(hub_span=1.2, beam_b=0.0508, beam_t=0.003175,
                                       beam_ext=0.1))
        self.assertAlmostEqual(N["m_clear"].value, mdl["m_design"], delta=1e-6)

    def test_slope_term_past_weight(self):
        # numeric check done separately: F=1000, a=.3, l=1.2, EI=2e5 -> slope 8.25e-4 rad
        self.assertAlmostEqual(tc.overhang_tip_slope(1000, .3, 1.2, 1.0, 2e5), 8.25e-4)

    def test_roll_check(self):
        C = tc.compute(base())[1]
        ms = next(c for c in C if c.label.startswith("MS_roll"))
        self.assertEqual(ms.status, tc.PASS)
        self.assertAlmostEqual(ms.margin, 1 / 0.80705 - 1, delta=1e-3)
        C = tc.compute(base(mass=150))[1]   # 1345 N·m -> 1.345 deg > 1 deg
        self.assertEqual(next(c for c in C if c.label.startswith("MS_roll")).status, tc.FAIL)

    def test_blank_zero_negative(self):
        v = base(); v["floor_clear"] = None
        N, C, _, _ = tc.compute(v)
        self.assertNotIn("front_hub", N)
        self.assertEqual(next(c for c in C if c.label == "Clearance at this load").status,
                         tc.NEED)
        for k, x in (("beam_h", 0.0), ("lever", -1.0), ("k_ref", 0.0), ("mass", float("nan"))):
            N, C, bad, _ = tc.compute(base(**{k: x}))   # must not raise
            self.assertIn(k, bad)

    def test_zero_clearance_allowed(self):
        N, _, bad, _ = tc.compute(base(floor_clear=0.0))
        self.assertFalse(bad)
        self.assertIn("front_hub", N)


class LoadSweep(unittest.TestCase):
    def st(self, m, **kw):
        return {c.label: c for c in tc.compute(base(**kw), test_mass=m)[1]}

    def test_planned_mass_passes(self):
        c = self.st(90)
        self.assertEqual(c["Clearance at this load"].status, tc.PASS)
        self.assertEqual(c["Above the floor at this load"].status, tc.PASS)

    def test_clearance_mass_is_the_roll_limit_mass(self):
        # heights sized for 1 deg -> clearance reached at m = K*1/(g*L) = 111.52 kg
        N = tc.compute(base())[0]
        self.assertAlmostEqual(N["m_clear"].value, 1000 / (9.80665 * 0.9144), delta=0.01)

    def test_overload_fails_and_floor_contact_fails(self):
        c = self.st(130)
        self.assertEqual(c["Clearance at this load"].status, tc.FAIL)
        self.assertEqual(c["MS_clearance (mass)"].status, tc.FAIL)
        m_floor = tc.compute(base())[0]["m_floor"].value
        c = self.st(m_floor * 1.05)
        self.assertEqual(c["Above the floor at this load"].status, tc.FAIL)   # the bug you saw

    def test_beam_end_past_weight_is_lower(self):
        # extending the beam past the weight point lowers its far corner -> hubs higher
        a = tc.compute(base())[0]["front_hub"].value
        b = tc.compute(base(beam_ext=0.1))[0]["front_hub"].value
        self.assertAlmostEqual(b - a, 0.1 * math.sin(math.radians(1.0)), places=9)

    def test_unrealistic_rotation_flagged(self):
        c = self.st(90, extra_rot=12.0)
        self.assertEqual(c["Design rotation is realistic"].status, tc.FAIL)

    def test_zero_mass(self):
        c = self.st(0.0)
        self.assertEqual(c["Clearance at this load"].status, tc.PASS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
