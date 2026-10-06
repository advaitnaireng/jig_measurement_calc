"""
TR Jig Height Calculator — Longhorn Racing Electric (Orion)
Run:  streamlit run app.py

All math lives in tr_calc.py. This file is only the interface.
This calculator does NOT certify the fixture's structural safety.
"""
import math

import plotly.graph_objects as go
import streamlit as st

import tr_calc as tc

st.set_page_config(page_title="TR Jig Height Calculator", layout="wide")

st.markdown("""
<style>
.card{background:#1B2431;border:1px solid #2A3646;border-radius:10px;padding:12px 14px;margin-bottom:12px}
.card .lbl{font-size:.82rem;opacity:.85}
.card .big{font-size:2rem;font-weight:600;line-height:1.25}
.badge{display:inline-block;padding:1px 9px;border-radius:999px;font-size:.75rem;
       font-weight:600;margin-right:6px}
.b-pass{background:#1f4d2e;color:#5ee38a}
.b-fail{background:#5a1f22;color:#ff7b7b}
.b-need{background:#4d4219;color:#ffd75e}
.b-prov{background:#4d4219;color:#ffd75e}
.why{font-size:.78rem;opacity:.75;margin-top:6px;line-height:1.35}
</style>""", unsafe_allow_html=True)

st.title("TR Jig Height Calculator")
st.caption("You set the floor clearance and beam section height. The app sizes the front hub, beam, rear hub and rear stand heights from them.")


# ---------------------------------------------------------------------------
# Input helper: stores SI values; widgets show the chosen unit system
# ---------------------------------------------------------------------------
def num_input(key, system):
    s = tc.SPEC[key]
    store = st.session_state.setdefault("si", {})
    store.setdefault(key, s.default)
    wk = f"w_{key}_{system}"
    init = st.session_state.get(wk, tc.to_disp(s.kind, store[key], system))
    tag = ""
    if store[key] is None:
        tag = "  :orange[input required]"
    elif s.status == tc.PROV and s.default is not None and \
            math.isclose(store[key], s.default, rel_tol=1e-9):
        tag = "  :orange[provisional]"
    x = st.number_input(f"{s.label} ({tc.unit(s.kind, system)}){tag}", value=init,
                        key=wk, help=s.help, format="%.4f")
    store[key] = tc.from_disp(s.kind, x, system)
    return store[key]


# ---------------------------------------------------------------------------
# Layout: results left, inputs right (like the seat-bottom calculator)
# ---------------------------------------------------------------------------
tab_calc, tab_notes = st.tabs(["Height stack", "Equations & assumptions"])

with tab_calc:
    left, right = st.columns([2.3, 1], gap="large")

    with right:
        st.subheader("Variable inputs")
        system = st.radio("Units", [tc.METRIC, tc.IMPERIAL], horizontal=True,
                          help="Inputs and results switch together. Math is always SI.")
        if st.button("Reset all to defaults"):
            st.session_state.clear()
            st.rerun()
        vals = {}
        groups = []
        for s in tc.INPUTS:
            if s.group not in groups:
                groups.append(s.group)
        for g in groups:
            box = st.container() if g == "Your choices" else \
                st.expander(g, expanded=(g == "Load & roll"))
            with box:
                if g == "Your choices":
                    st.markdown("**Your choices**")
                for s in tc.INPUTS:
                    if s.group == g:
                        vals[s.key] = num_input(s.key, system)

    N0, _, _, model0 = tc.compute(vals, system)

    with left:
        cls = {tc.PASS: "b-pass", tc.FAIL: "b-fail", tc.NEED: "b-need"}
        u = 1000 if system == tc.METRIC else 1 / tc.M_PER_IN
        ul = tc.unit("length", system)

        def card(col, label, big, badges, why, size="2rem"):
            col.markdown(f'<div class="card"><div class="lbl">{label}</div>'
                         f'<div class="big" style="font-size:{size}">{big}</div>{badges}'
                         f'<div class="why">{why}</div></div>', unsafe_allow_html=True)

        # ---------- design heights (do not depend on the slider) ----------
        st.subheader("Heights the jig needs")
        heads = [n for n in N0.values() if n.headline]
        if heads:
            cols = st.columns(3)
            for i, n in enumerate(heads):
                card(cols[i % 3], n.label, tc.fmt(n.kind, n.value, system), "", n.why)
        else:
            st.info("Enter your floor clearance and beam section height on the right.")

        # ---------- load slider ----------
        st.subheader("Add weight")
        test_mass = None
        if model0:
            m_plan = vals["mass"]
            top = model0["m_floor"] * 1.15 if model0["m_floor"] else 3 * m_plan
            top_d = max(1.0, round(tc.to_disp("mass", top, system)))
            plan_d = min(top_d, round(tc.to_disp("mass", m_plan, system), 1))
            md = st.slider(f"Applied mass ({tc.unit('mass', system)})", 0.0, float(top_d),
                           float(plan_d), step=max(0.5, top_d / 400),
                           help="Drag to add weight. Each step: torque = m·g·L, roll = T/K, then "
                                "the beam end drops and the clearance is re-checked. Starts at "
                                "your planned max mass.")
            test_mass = tc.from_disp("mass", md, system)
        N, C, bad, model = tc.compute(vals, system, test_mass)

        st.subheader("Checks at this load")
        cols = st.columns(3)
        for i, ch in enumerate(C):
            if ch.margin is None:
                big = "—"
            elif ch.kind == "ratio":
                big = f"{ch.margin:+.2f}"
            else:
                big = tc.fmt("length", ch.margin, system)
            prov = '<span class="badge b-prov">PROVISIONAL</span>' if ch.provisional else ""
            card(cols[i % 3], ch.label, big,
                 f'<span class="badge {cls[ch.status]}">{ch.status}</span>{prov}', ch.why)
        n_fail = sum(c.status == tc.FAIL for c in C)
        n_need = sum(c.status == tc.NEED for c in C)
        if n_fail:
            st.error(f"{n_fail} check(s) failing at this load.")
        if n_need:
            st.warning(f"{n_need} check(s) waiting on inputs.")
        if not n_fail and not n_need:
            st.success("All checks pass at this load.")
        if any(c.provisional for c in C):
            st.warning("Some results use provisional values (yellow tag). Confirm them before "
                       "treating a PASS as final.")

        if model:
            # ---------- front view at the TRUE rotation for this mass ----------
            st.subheader("Front view at this load (true scale, no exaggeration)")
            th = model["theta_at"](test_mass)
            hf, L, bh = model["hub"], vals["lever"], vals["beam_h"]
            fix, bcl = model["fix"], model["hub"] - model["fix"] - vals["beam_h"] / 2
            span = vals.get("hub_span") or 0.6 * L
            sag = model["bend_per_N"] * test_mass * vals["g"]
            t = -math.radians(th)

            def rot(y, z):
                dz = z - hf
                return (y * math.cos(t) - dz * math.sin(t), hf + y * math.sin(t) + dz * math.cos(t))

            fig = go.Figure()

            def poly(p, **kw):
                fig.add_trace(go.Scatter(x=[q[0] * u for q in p], y=[q[1] * u for q in p], **kw))

            yend = L + vals["beam_ext"]
            xr = [-span / 2 - 0.15, yend + 0.15]
            poly([(xr[0], 0), (xr[1], 0)], mode="lines", line=dict(color="#888", width=4),
                 name="Floor")
            c = vals["floor_clear"]
            poly([(xr[0], c), (xr[1], c)], mode="lines", line=dict(color="#ffd75e", dash="dot"),
                 name="Your clearance")
            y0 = -span / 2 - 0.05
            rect = [(y0, bcl + bh / 2), (yend, bcl + bh / 2), (yend, bcl - bh / 2),
                    (y0, bcl - bh / 2), (y0, bcl + bh / 2)]
            poly(rect, mode="lines", line=dict(color="#4ea8de", dash="dot"), name="Beam, no load")
            r = [rot(*q) for q in rect]
            # bending sag grows toward the loaded end (drawn linearly from the near hub)
            Fm = test_mass * vals["g"]

            def sag_at(y):   # 0 at the near hub, full sag at L, plus slope past L
                if y <= span / 2:
                    return 0.0
                if y <= L:
                    return sag * (y - span / 2) / max(1e-9, L - span / 2)
                return sag + Fm * model["slope_per_N"] * (y - L)
            r = [(q[0], q[1] - sag_at(q[0])) for q in r]
            low = model["low_height"](test_mass)
            color = "#e05d5d" if low < c else "#4ea8de"
            poly(r, fill="toself", mode="lines", line=dict(color=color), name="Beam at this load")
            if vals["w_below"] > 0:
                wb = [(L - .05, bcl - bh / 2), (L + .05, bcl - bh / 2),
                      (L + .05, bcl - bh / 2 - vals["w_below"]),
                      (L - .05, bcl - bh / 2 - vals["w_below"]), (L - .05, bcl - bh / 2)]
                poly([(q[0], q[1] - sag) for q in map(lambda p: rot(*p), wb)], fill="toself",
                     mode="lines", line=dict(color="#e0a05d"), name="Weight")
            R = vals["front_hub_D"] / 2
            for yy in (-span / 2, span / 2):
                circ = [rot(yy + R * math.cos(k / 20 * math.pi), hf + R * math.sin(k / 20 * math.pi))
                        for k in range(41)]
                poly(circ, mode="lines", line=dict(color="#5ee38a"), showlegend=False)
            poly([(0, hf)], mode="markers", marker=dict(size=9, color="#5ee38a"),
                 name="Front hub axis (pivot)")
            fig.add_annotation(x=yend * u, y=low * u, showarrow=True, ay=40, arrowcolor=color,
                               text=f"lowest point {tc.fmt('length', low, system)}")
            fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#1B2431", height=380,
                              xaxis_title=f"lateral, from car centerline ({ul})",
                              yaxis_title=f"height above floor ({ul})",
                              yaxis=dict(scaleanchor="x"), margin=dict(l=10, r=10, t=10, b=10),
                              legend=dict(orientation="h"))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"Roll at this load: {th:.4f}°. Drawn at true angle. Sketch only, not CAD "
                       "or FEA.")

            # ---------- sweep: lowest point and roll vs mass ----------
            st.subheader("What happens as you keep adding weight")
            mmax = (model["m_floor"] or 3 * vals["mass"]) * 1.15
            ms = [mmax * k / 120 for k in range(121)]
            md_ = [tc.to_disp("mass", m, system) for m in ms]
            sw = go.Figure()
            sw.add_trace(go.Scatter(x=md_, y=[model["low_height"](m) * u for m in ms],
                                    name="Lowest point height", line=dict(color="#4ea8de")))
            sw.add_trace(go.Scatter(x=md_, y=[model["theta_at"](m) for m in ms], yaxis="y2",
                                    name="Roll (deg)", line=dict(color="#e0a05d", dash="dash")))
            sw.add_hline(y=c * u, line=dict(color="#ffd75e", dash="dot"),
                         annotation_text="your clearance")
            sw.add_hline(y=0, line=dict(color="#888"), annotation_text="floor")
            sw.add_vline(x=tc.to_disp("mass", test_mass, system),
                         line=dict(color="#ff7b7b"), annotation_text="slider")
            sw.add_vline(x=tc.to_disp("mass", vals["mass"], system),
                         line=dict(color="#5ee38a", dash="dot"), annotation_text="planned")
            sw.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#1B2431", height=340,
                             xaxis_title=f"applied mass ({tc.unit('mass', system)})",
                             yaxis_title=f"lowest point above floor ({ul})",
                             yaxis2=dict(title="roll (deg)", overlaying="y", side="right"),
                             margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h"))
            st.plotly_chart(sw, use_container_width=True)

            # ---------- rear stand with x and y ----------
            if "y" in N:
                st.subheader("Rear stand — x and y")
                x_, y_ = N["x"].value, N["y"].value
                Rr = vals["rear_hub_D"] / 2
                w = vals["rear_hub_D"] + 2 * vals["rear_top"]
                bt = max(vals["rear_top"], 0.006)
                rs = go.Figure()
                rsp = lambda p, **kw: rs.add_trace(go.Scatter(x=[q[0] * u for q in p],
                                                              y=[q[1] * u for q in p], **kw))
                rsp([(-w, 0), (w, 0), (w, bt), (-w, bt), (-w, 0)], fill="toself", mode="lines",
                    line=dict(color="#5ee38a"), name="Base")
                rsp([(-w * .7, bt), (w * .7, bt), (w / 2, x_), (w / 2, y_ - Rr * .3),
                     (0, y_), (-w / 2, y_ - Rr * .3), (-w / 2, x_), (-w * .7, bt)],
                    fill="toself", mode="lines", line=dict(color="#5ee38a"), name="Stand")
                rsp([(Rr * math.cos(k / 20 * math.pi), x_ + Rr * math.sin(k / 20 * math.pi))
                     for k in range(41)], mode="lines", line=dict(color="#ddd"), name="Rear hub")
                for xx, top, lab in ((w * 1.2, x_, "x"), (w * 1.6, y_, "y")):
                    rsp([(xx, 0), (xx, top)], mode="lines+markers", showlegend=False,
                        line=dict(color="#ff7b7b"))
                    rs.add_annotation(x=xx * u, y=top / 2 * u, showarrow=False, xshift=40,
                                      text=f"{lab} = {tc.fmt('length', top, system)}",
                                      font=dict(color="#ff7b7b"))
                rsp([(0, x_), (w * 1.2, x_)], mode="lines", showlegend=False,
                    line=dict(color="#ff7b7b", dash="dot"))
                rs.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#1B2431", height=380,
                                 yaxis=dict(scaleanchor="x", title=f"height ({ul})"),
                                 xaxis=dict(visible=False), margin=dict(l=10, r=10, t=10, b=10),
                                 showlegend=False)
                st.plotly_chart(rs, use_container_width=True)
                st.caption("x is floor to rear hub center and must equal the front hub height. "
                           "y is the full stand height. Shape is schematic.")

        st.subheader("Where the numbers come from")
        cols = st.columns(2)
        for i, n in enumerate([n for n in N.values() if not n.headline]):
            val = tc.fmt(n.kind, n.value, system) if n.value is not None else "not included"
            card(cols[i % 2], n.label, val, "", n.why, size="1.4rem")

with tab_notes:
    st.markdown("""
**How the heights are built (bottom up)**

1. Floor → your clearance → the lowest point at full rotation.
2. As the beam turns θ about the front hub axis, the lowest point drops by
   L·sin θ + depth·cos θ − depth (+ beam bending if entered).
3. Lowest point → beam bottom → beam height → beam top → fixture base → front hub radius → **front hub center**.
   - Front hub height = clearance + L·sin θ + depth·cos θ + bending
   - depth = (fixture base + front hub radius) + beam height + weight below beam
4. **Beam centerline** = front hub − fixture − beam height/2
5. **Rear hub center** = front hub center (car level)
6. **Rear stand height** = rear hub center + rear hub radius + material above

**Other equations**
- F = m·g, T = F·L, θ = T/K, MS_roll = θ_max/θ − 1
- Design rotation = larger of θ_max and θ, plus the extra allowance
- Optional bending: δ = F·a²·(l + a)/(3·E·I), a = L − l/2, rectangular-tube I

**Assumptions**
1. The front end, beam and weight rotate rigidly about the front hub axis at the car centerline.
2. The front hubs sit on top of the beam through a fixture.
3. The car is level: rear hubs at the same height as the front.
4. The weight's lowest point is the beam bottom unless you enter how far it hangs below it.
5. Heights are sized so the lowest point sits at your clearance at the roll limit. The slider then checks any other mass: roll = m·g·L/K, plus the allowance scaled with load.\n7. The lowest point is the beam's far bottom corner or the weight bottom, whichever is lower.\n8. The rotation pivot is at the car centerline. Moving it between the hub axis and the beam centerline changes the result by well under 0.1 mm at 1°.
6. Bending treats the two front fixtures as simple supports. A first estimate, not FEA.

**This calculator does not certify the fixture's structural safety.**
""")
