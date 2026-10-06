# TR Jig Height Calculator — Longhorn Racing Electric (Orion)

Checks the height stack of the torsional-rigidity jig: rear hub height, front hub
height, roll (predicted twist), loading-beam height, and how far the beam and weight
swing toward the floor. Every check shows a margin, PASS / FAIL / NEEDS INPUT, and the
equation with your numbers plugged in.

**This calculator does not certify the fixture's structural safety.** It is a
geometry and planning tool. The sketch is not CAD or FEA.

## Run

    pip install -r requirements.txt
    streamlit run app.py

Run the formula tests:

    python -m unittest test_tr_calc.py

## Files

- `app.py`: Streamlit interface (dark theme, results left, inputs right)
- `tr_calc.py`: every constant, default, equation and check
- `test_tr_calc.py`: hand-calculated validation, plus zero, missing and invalid input tests
- `.streamlit/config.toml`: dark theme

## How it works

You enter two numbers:
- **Floor clearance**: how high the lowest point stays at full rotation.
- **Loading-beam section height**: the cross-section height, not the beam's length.

The app sizes the rest, bottom up:

    front hub = clearance + L·sin θ + depth·cos θ (+ beam bending)
    depth     = (fixture base + front hub radius) + beam height + weight below beam
    beam CL   = front hub − (fixture base + front hub radius) − beam height/2
    rear hub  = front hub                              (car level)
    stand     = rear hub + rear hub radius + material above hub

Here θ is the larger of the roll limit and the predicted roll (T/K), plus an optional
allowance. The front hubs sit on top of the beam through a fixture.

The other inputs (mass, lever, K, hub diameters, fixture material, how far the weight
hangs below the beam, and the optional bending inputs) keep provisional defaults in
collapsible sections. They are marked yellow until you change them.

Example with 25.4 mm clearance and a 76.2 mm beam, everything else at its default:
front and rear hub 184.2 mm, beam centerline 79.4 mm, rear stand 250.9 mm, and the
beam end drops 15.9 mm.

## Assumptions

1. The front end, beam and weight rotate rigidly about the front hub axis at the car centerline.
2. The car is level, so the rear hub height equals the front.
3. Unless you enter "weight hangs below beam bottom", the beam bottom is the lowest point.
   Full-size plates centered on the beam hang far lower, so enter that value if you use them.
4. Clearance is designed for the roll limit, the worst case you allow.
5. Optional bending treats the front fixtures as simple supports: δ = F·a²(l+a)/(3EI).
6. The front hub diameter defaults to the rear's 4.25 in until it is measured.

**This calculator does not certify the fixture's structural safety.**
