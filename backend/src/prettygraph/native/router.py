"""Deterministic orthogonal edge router ported from drawio-ai-kit builder.mjs.

Same three libavoid-style stages: (1) orthogonal visibility graph, (2) A*
shortest path through the gaps between cards, (3) NUDGE — spread parallel
overlapping segments onto distinct tracks. A line never cuts through an icon and
parallel runs never overlap; the result is independent of link() order.

``build_edges(d)`` consumes ``d.R`` (rect registry with ``.ob`` obstacle flags)
and ``d.edge_specs``, appends edge cells to ``d.cells``, and records
``d._cross`` / ``d._overlaps`` residuals for verification.
"""

from __future__ import annotations

import math

from .theme import THEME


def _r(v: float) -> int:
    """JS Math.round (half up toward +inf) — keeps geometry byte-identical to the kit."""
    return math.floor(v + 0.5)


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def build_edges(d) -> None:
    specs = d.edge_specs
    R = lambda i: d.R[i]

    cards = [{"id": i, "x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]}
             for i, r in d.R.items() if r.get("ob")]
    M = 7

    def seg_hit(p, q, ex):
        for c in cards:
            if c["id"] in ex:
                continue
            x0, x1 = c["x"] - M, c["x"] + c["w"] + M
            y0, y1 = c["y"] - M, c["y"] + c["h"] + M
            if abs(p["y"] - q["y"]) < 1:
                if y0 < p["y"] < y1 and min(p["x"], q["x"]) < x1 and max(p["x"], q["x"]) > x0:
                    return True
            elif abs(p["x"] - q["x"]) < 1:
                if x0 < p["x"] < x1 and min(p["y"], q["y"]) < y1 and max(p["y"], q["y"]) > y0:
                    return True
            else:
                if (min(p["x"], q["x"]) < x1 and max(p["x"], q["x"]) > x0
                        and min(p["y"], q["y"]) < y1 and max(p["y"], q["y"]) > y0):
                    return True
        return False

    def path_hit(pp, ex):
        return any(seg_hit(pp[i], pp[i + 1], ex) for i in range(len(pp) - 1))

    containers = [r for r in d.R.values() if r.get("ob") is False]

    def enclosing(n, other=None):
        best = None
        for c in containers:
            if (c["x"] <= n["x"] + 1 and c["y"] <= n["y"] + 1
                    and c["x"] + c["w"] >= n["x"] + n["w"] - 1
                    and c["y"] + c["h"] >= n["y"] + n["h"] - 1
                    and c["w"] * c["h"] > n["w"] * n["h"] + 1):
                if other:
                    enc_other = (c["x"] <= other["x"] + 1 and c["y"] <= other["y"] + 1
                                 and c["x"] + c["w"] >= other["x"] + other["w"] - 1
                                 and c["y"] + c["h"] >= other["y"] + other["h"] - 1)
                    if enc_other:
                        continue
                    if not best or c["w"] * c["h"] > best["w"] * best["h"]:
                        best = c
                else:
                    if not best or c["w"] * c["h"] < best["w"] * best["h"]:
                        best = c
        return best

    BM = 24

    def inside_any(px, py):
        return any(c["x"] + 1 < px < c["x"] + c["w"] - 1 and c["y"] + 1 < py < c["y"] + c["h"] - 1
                   for c in containers)

    def _encloses(c, r):
        return (c["x"] <= r["x"] + 1 and c["y"] <= r["y"] + 1
                and c["x"] + c["w"] >= r["x"] + r["w"] - 1
                and c["y"] + c["h"] >= r["y"] + r["h"] - 1)

    def along(p, q, a=None, b=None):
        if abs(p["x"] - q["x"]) < 1:
            y0, y1 = min(p["y"], q["y"]), max(p["y"], q["y"])
            if y1 - y0 < 28:
                return False
            if not inside_any(p["x"], (y0 + y1) / 2):
                for c in containers:
                    for bx in (c["x"], c["x"] + c["w"]):
                        if abs(p["x"] - bx) < BM and min(y1, c["y"] + c["h"]) - max(y0, c["y"]) > 28:
                            return True
            if a and b:
                for c in containers:
                    if (c["x"] + 8 < p["x"] < c["x"] + c["w"] - 8
                            and min(y1, c["y"] + c["h"]) - max(y0, c["y"]) > 28):
                        if _encloses(c, a) != _encloses(c, b):
                            return True
        else:
            x0, x1 = min(p["x"], q["x"]), max(p["x"], q["x"])
            if x1 - x0 < 28:
                return False
            if not inside_any((x0 + x1) / 2, p["y"]):
                for c in containers:
                    for by in (c["y"], c["y"] + c["h"]):
                        if abs(p["y"] - by) < BM and min(x1, c["x"] + c["w"]) - max(x0, c["x"]) > 28:
                            return True
            if a and b:
                for c in containers:
                    if (c["y"] + 8 < p["y"] < c["y"] + c["h"] - 8
                            and min(x1, c["x"] + c["w"]) - max(x0, c["x"]) > 28):
                        if _encloses(c, a) != _encloses(c, b):
                            return True
        return False

    def path_along(pp, a=None, b=None):
        return any(along(pp[i], pp[i + 1], a, b) for i in range(len(pp) - 1))

    def pt(n, sd, f):
        if sd == "L":
            return {"x": n["x"], "y": _r(n["y"] + f * n["h"])}
        if sd == "R":
            return {"x": n["x"] + n["w"], "y": _r(n["y"] + f * n["h"])}
        if sd == "T":
            return {"x": _r(n["x"] + f * n["w"]), "y": n["y"]}
        return {"x": _r(n["x"] + f * n["w"]), "y": n["y"] + n["h"]}

    def geom(a, b, r, sf, tf):
        sp, ep = pt(a, r["es"], sf), pt(b, r["en"], tf)
        wp = []
        kind = r["kind"]
        if kind == "Zx":
            wp = [{"x": r["lane"], "y": sp["y"]}, {"x": r["lane"], "y": ep["y"]}]
        elif kind == "Zy":
            wp = [{"x": sp["x"], "y": r["lane"]}, {"x": ep["x"], "y": r["lane"]}]
        elif kind == "Lhv":
            wp = [{"x": ep["x"], "y": sp["y"]}]
        elif kind == "Lvh":
            wp = [{"x": sp["x"], "y": ep["y"]}]
        elif kind == "poly":
            wp = r["pts"]
        return {"sp": sp, "ep": ep, "wp": wp}

    def clear_w(a, b, r, sf, tf, ex):
        g = geom(a, b, r, sf, tf)
        return not path_hit([g["sp"], *g["wp"], g["ep"]], ex)

    def gap_sweep(lo, hi):
        out = []
        mid = (lo + hi) / 2
        out.append(_r(mid))
        for k in range(1, 31):
            u, dn = mid + k * 10, mid - k * 10
            if dn > lo + 2:
                out.append(_r(dn))
            if u < hi - 2:
                out.append(_r(u))
        return out

    # A. facing sides + axis per edge
    face = []
    for e in specs:
        o = e["opts"]
        if o.get("style"):
            face.append(None)
            continue
        if o.get("route"):
            rt = o["route"]
            face.append({"es": rt["es"], "en": rt["en"],
                         "horiz": rt["es"] in ("L", "R")})
            continue
        a, b = R(e["src"]), R(e["tgt"])
        fwd_x = b["x"] + b["w"] / 2 >= a["x"] + a["w"] / 2
        fwd_y = b["y"] + b["h"] / 2 >= a["y"] + a["h"] / 2
        x_ov = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
        y_ov = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
        if o.get("dir"):
            horiz = o["dir"] == "LR"
        else:
            horiz = True if y_ov > 8 else (False if x_ov > 8
                    else abs(b["x"] - a["x"]) >= abs(b["y"] - a["y"]))
        if horiz:
            face.append({"es": "R" if fwd_x else "L", "en": "L" if fwd_x else "R", "horiz": True})
        else:
            face.append({"es": "B" if fwd_y else "T", "en": "T" if fwd_y else "B", "horiz": False})

    frac = [{"s": 0.5, "t": 0.5} for _ in specs]

    def decollide(idxs, side_of):
        grp = {}
        for i in idxs:
            for end in ("s", "t"):
                sd = side_of(i, end)
                if not sd:
                    continue
                node = specs[i]["src"] if end == "s" else specs[i]["tgt"]
                grp.setdefault(f"{node}|{sd}", []).append({"i": i, "end": end})

        def set_f(it, f):
            frac[it["i"]]["s" if it["end"] == "s" else "t"] = f

        for k, arr in grp.items():
            if len(arr) < 2:
                continue
            side = k[k.rfind("|") + 1:]
            v = side in ("L", "R")
            node = R(k[:k.rfind("|")])
            nc = node["y"] + node["h"] / 2 if v else node["x"] + node["w"] / 2
            info = []
            for it in arr:
                far = R(specs[it["i"]]["tgt" if it["end"] == "s" else "src"])
                fc = far["y"] + far["h"] / 2 if v else far["x"] + far["w"] / 2
                info.append({"it": it, "fc": fc})
            al = [x for x in info if abs(x["fc"] - nc) < 8]
            if len(al) == 1 and len(arr) <= 3:
                set_f(al[0]["it"], 0.5)
                rest = [x for x in info if x is not al[0]]
                lo = sorted([x for x in rest if x["fc"] <= nc], key=lambda A: -A["fc"])
                hi = sorted([x for x in rest if x["fc"] > nc], key=lambda A: A["fc"])
                for j, x in enumerate(lo):
                    set_f(x["it"], 0.3 - j * 0.14)
                for j, x in enumerate(hi):
                    set_f(x["it"], 0.7 + j * 0.14)
            else:
                info.sort(key=lambda A: A["fc"])
                for j, x in enumerate(info):
                    set_f(x["it"], (j + 1) / (len(arr) + 1))

    all_idx = [i for i in range(len(specs)) if face[i]]
    decollide(all_idx, lambda i, end: (face[i]["es"] if end == "s" else face[i]["en"]))

    used = set()
    used_segs = []

    def used_key(x1, y1, x2, y2):
        return (f"{x1},{y1}|{x2},{y2}" if (x1 < x2 or y1 < y2)
                else f"{x2},{y2}|{x1},{y1}")

    def reg(g):
        pp = [g["sp"], *g["wp"], g["ep"]]
        for k in range(len(pp) - 1):
            used.add(used_key(_r(pp[k]["x"]), _r(pp[k]["y"]),
                              _r(pp[k + 1]["x"]), _r(pp[k + 1]["y"])))
            used_segs.append({"x1": pp[k]["x"], "y1": pp[k]["y"],
                              "x2": pp[k + 1]["x"], "y2": pp[k + 1]["y"]})

    def ov1(a0, a1, b0, b1):
        return min(a1, b1) - max(a0, b0)

    def overlaps_used(pp):
        for i in range(len(pp) - 1):
            a, b = pp[i], pp[i + 1]
            for s in used_segs:
                if abs(a["x"] - b["x"]) < 1 and abs(s["x1"] - s["x2"]) < 1 and abs(a["x"] - s["x1"]) < 6:
                    if ov1(min(a["y"], b["y"]), max(a["y"], b["y"]),
                           min(s["y1"], s["y2"]), max(s["y1"], s["y2"])) > 14:
                        return True
                elif abs(a["y"] - b["y"]) < 1 and abs(s["y1"] - s["y2"]) < 1 and abs(a["y"] - s["y1"]) < 6:
                    if ov1(min(a["x"], b["x"]), max(a["x"], b["x"]),
                           min(s["x1"], s["x2"]), max(s["x1"], s["x2"])) > 14:
                        return True
        return False

    # A* channel router (fallback)
    def astar(a, b, es, en, sf, tf, ex):
        def pp_port(n, sd, f):
            if sd == "L":
                return {"x": n["x"], "y": _r(n["y"] + f * n["h"]), "dx": -1, "dy": 0}
            if sd == "R":
                return {"x": n["x"] + n["w"], "y": _r(n["y"] + f * n["h"]), "dx": 1, "dy": 0}
            if sd == "T":
                return {"x": _r(n["x"] + f * n["w"]), "y": n["y"], "dx": 0, "dy": -1}
            return {"x": _r(n["x"] + f * n["w"]), "y": n["y"] + n["h"], "dx": 0, "dy": 1}

        sp, ep, off = pp_port(a, es, sf), pp_port(b, en, tf), 24

        def push_off(port, n, other):
            c = enclosing(n, other)
            default = {"x": port["x"] + port["dx"] * off, "y": port["y"] + port["dy"] * off}
            if not c:
                return default
            if port["dx"] < 0:
                cand = {"x": c["x"] - off, "y": port["y"]}
            elif port["dx"] > 0:
                cand = {"x": c["x"] + c["w"] + off, "y": port["y"]}
            elif port["dy"] < 0:
                cand = {"x": port["x"], "y": c["y"] - off}
            else:
                cand = {"x": port["x"], "y": c["y"] + c["h"] + off}
            return default if seg_hit(port, cand, ex) else cand

        s0, g0 = push_off(sp, a, b), push_off(ep, b, a)
        xs = {s0["x"], g0["x"], sp["x"], ep["x"]}
        ys = {s0["y"], g0["y"], sp["y"], ep["y"]}
        for c in cards:
            if c["id"] in ex:
                continue
            xs.update((c["x"] - M, c["x"] + c["w"] + M))
            ys.update((c["y"] - M, c["y"] + c["h"] + M))
        for c in containers:
            xs.update((c["x"] - M, c["x"] + c["w"] + M))
            ys.update((c["y"] - M, c["y"] + c["h"] + M))
        X, Y = sorted(xs), sorted(ys)
        new_x, new_y = set(X), set(Y)
        step, margin = 20, 24
        for k in range(len(X) - 1):
            gap = X[k + 1] - X[k]
            if gap >= 2 * margin + 8:
                available = gap - 2 * margin
                # int(): upgrade-ingested cards carry float geometry, and a
                # float // yields float — range() would raise.
                num_lanes = int(available // step) + 1
                if num_lanes > 0:
                    occupied = (num_lanes - 1) * step
                    left = _r((gap - occupied) / 2)
                    for i in range(num_lanes):
                        new_x.add(X[k] + left + i * step)
            elif gap > 32:
                new_x.add(_r((X[k] + X[k + 1]) / 2))
        for k in range(len(Y) - 1):
            gap = Y[k + 1] - Y[k]
            if gap >= 2 * margin + 8:
                available = gap - 2 * margin
                num_lanes = int(available // step) + 1
                if num_lanes > 0:
                    occupied = (num_lanes - 1) * step
                    left = _r((gap - occupied) / 2)
                    for i in range(num_lanes):
                        new_y.add(Y[k] + left + i * step)
            elif gap > 32:
                new_y.add(_r((Y[k] + Y[k + 1]) / 2))
        X, Y = sorted(new_x), sorted(new_y)

        xI = {v: i for i, v in enumerate(X)}
        yI = {v: i for i, v in enumerate(Y)}
        W = len(X)

        def idx(i, j):
            return j * W + i

        gi, gj = xI[g0["x"]], yI[g0["y"]]
        start = idx(xI[s0["x"]], yI[s0["y"]])
        goal = idx(gi, gj)

        def seg_ok(x1, y1, x2, y2):
            return not seg_hit({"x": x1, "y": y1}, {"x": x2, "y": y2}, ex)

        def check_crossing(cx, cy, nx, ny):
            is_horiz = abs(cy - ny) < 1
            x0, x1 = min(cx, nx), max(cx, nx)
            y0, y1 = min(cy, ny), max(cy, ny)
            crossings = 0
            for s in used_segs:
                s_horiz = abs(s["y1"] - s["y2"]) < 1
                if is_horiz and not s_horiz:
                    sx = s["x1"]
                    if x0 < sx < x1 and min(s["y1"], s["y2"]) < cy < max(s["y1"], s["y2"]):
                        crossings += 1
                elif not is_horiz and s_horiz:
                    sy = s["y1"]
                    if y0 < sy < y1 and min(s["x1"], s["x2"]) < cx < max(s["x1"], s["x2"]):
                        crossings += 1
            return crossings

        def heur(n):
            i = n % W
            j = (n - i) // W
            return abs(X[i] - X[gi]) + abs(Y[j] - Y[gj])

        import heapq
        gsc = {start: 0}
        came, cdir = {}, {}
        heap = [(heur(start), start)]
        found, guard = False, 0
        while heap and guard < 60000:
            guard += 1
            fs, cur = heapq.heappop(heap)
            if fs > gsc[cur] + heur(cur) + 1e-6:
                continue
            if cur == goal:
                found = True
                break
            ci = cur % W
            cj = (cur - ci) // W
            cx, cy = X[ci], Y[cj]
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = ci + di, cj + dj
                if ni < 0 or nj < 0 or ni >= W or nj >= len(Y):
                    continue
                nx, ny = X[ni], Y[nj]
                if not seg_ok(cx, cy, nx, ny):
                    continue
                nid = idx(ni, nj)
                nd = "h" if di != 0 else "v"
                cost = (abs(nx - cx) + abs(ny - cy)
                        + (80 if cdir.get(cur) and cdir.get(cur) != nd else 0)
                        + (400 if used_key(cx, cy, nx, ny) in used else 0)
                        + (220 if along({"x": cx, "y": cy}, {"x": nx, "y": ny}, a, b) else 0)
                        + check_crossing(cx, cy, nx, ny) * 250)
                ng = gsc[cur] + cost
                if nid not in gsc or ng < gsc[nid]:
                    gsc[nid] = ng
                    came[nid] = cur
                    cdir[nid] = nd
                    heapq.heappush(heap, (ng + heur(nid), nid))
        if not found:
            return None
        path, c = [], goal
        while c is not None:
            i = c % W
            j = (c - i) // W
            path.append({"x": X[i], "y": Y[j]})
            c = came.get(c)
        path.reverse()
        simp = [path[0]]
        for k in range(1, len(path) - 1):
            p, q, rr = simp[-1], path[k], path[k + 1]
            if (p["x"] == q["x"] and q["x"] == rr["x"]) or (p["y"] == q["y"] and q["y"] == rr["y"]):
                continue
            simp.append(q)
        simp.append(path[-1])
        return {"es": es, "en": en, "kind": "poly", "pts": simp, "cost": gsc[goal]}

    # B. route each edge
    routes = [None] * len(specs)

    def heuristic(e, i, strict):
        a, b = R(e["src"]), R(e["tgt"])
        ex = {e["src"], e["tgt"]}
        f = face[i]
        sf, tf = frac[i]["s"], frac[i]["t"]

        def try_r(r):
            if not clear_w(a, b, r, sf, tf, ex):
                return None
            g = geom(a, b, r, sf, tf)
            pp = [g["sp"], *g["wp"], g["ep"]]
            if path_along(pp, a, b):
                return None
            if strict and overlaps_used(pp):
                return None
            return r

        r = None
        if f["horiz"]:
            if abs(a["y"] + sf * a["h"] - (b["y"] + tf * b["h"])) < 2:
                r = try_r({"es": f["es"], "en": f["en"], "kind": "straight"})
            if not r:
                lo = min(a["x"] + a["w"], b["x"] + b["w"])
                hi = max(a["x"], b["x"])
                for lx in gap_sweep(lo, hi):
                    r = try_r({"es": f["es"], "en": f["en"], "kind": "Zx", "lane": lx})
                    if r:
                        break
            if not r:
                fwd = b["y"] + b["h"] / 2 >= a["y"] + a["h"] / 2
                for cand in ({"es": f["es"], "en": "T" if fwd else "B", "kind": "Lhv"},
                             {"es": "B" if fwd else "T", "en": f["en"], "kind": "Lvh"}):
                    r = try_r(cand)
                    if r:
                        break
        else:
            if abs(a["x"] + sf * a["w"] - (b["x"] + tf * b["w"])) < 2:
                r = try_r({"es": f["es"], "en": f["en"], "kind": "straight"})
            if not r:
                lo = min(a["y"] + a["h"], b["y"] + b["h"])
                hi = max(a["y"], b["y"])
                for ly in gap_sweep(lo, hi):
                    r = try_r({"es": f["es"], "en": f["en"], "kind": "Zy", "lane": ly})
                    if r:
                        break
            if not r:
                fwd = b["x"] + b["w"] / 2 >= a["x"] + a["w"] / 2
                for cand in ({"es": f["es"], "en": "L" if fwd else "R", "kind": "Lvh"},
                             {"es": "R" if fwd else "L", "en": f["en"], "kind": "Lhv"}):
                    r = try_r(cand)
                    if r:
                        break
        return r

    need = []
    for i, e in enumerate(specs):
        o = e["opts"]
        if o.get("style"):
            routes[i] = {"raw": True}
            continue
        if o.get("route"):
            routes[i] = o["route"]
            reg(geom(R(e["src"]), R(e["tgt"]), routes[i], frac[i]["s"], frac[i]["t"]))
            continue
        r = heuristic(e, i, True) or heuristic(e, i, False)
        if r:
            routes[i] = r
            reg(geom(R(e["src"]), R(e["tgt"]), r, frac[i]["s"], frac[i]["t"]))
        else:
            need.append(i)

    # pass 2: A* for the rest
    port_used = {}

    def take_port(node, side, fv):
        port_used.setdefault(f"{node}|{side}", []).append(fv)

    for i, e in enumerate(specs):
        r = routes[i]
        if not r or r.get("raw"):
            continue
        take_port(e["src"], r["es"], frac[i]["s"])
        take_port(e["tgt"], r["en"], frac[i]["t"])

    def free_port(node, side, want):
        taken = port_used.get(f"{node}|{side}", [])
        for fv in (want, 0.5, 0.3, 0.7, 0.2, 0.8):
            if all(abs(t - fv) >= 0.12 for t in taken):
                return fv
        return want

    for i in need:
        e = specs[i]
        a, b = R(e["src"]), R(e["tgt"])
        ex = {e["src"], e["tgt"]}
        f = face[i]
        fwd_y = b["y"] + b["h"] / 2 >= a["y"] + a["h"] / 2
        fwd_x = b["x"] + b["w"] / 2 >= a["x"] + a["w"] / 2
        if f["horiz"]:
            tries = [[f["es"], f["en"]], ["T", "T"], ["B", "B"],
                     ["B" if fwd_y else "T", "L" if fwd_x else "R"]]
        else:
            tries = [[f["es"], f["en"]], ["L", "L"], ["R", "R"],
                     ["R" if fwd_x else "L", "T" if fwd_y else "B"]]
        best = None
        for es, en in tries:
            sf = free_port(e["src"], es, frac[i]["s"])
            tf = free_port(e["tgt"], en, frac[i]["t"])
            rr = astar(a, b, es, en, sf, tf, ex)
            if rr and (not best or rr["cost"] < best["r"]["cost"]):
                best = {"r": rr, "sf": sf, "tf": tf}
        if best:
            frac[i]["s"], frac[i]["t"] = best["sf"], best["tf"]
            routes[i] = {"es": best["r"]["es"], "en": best["r"]["en"],
                         "kind": "poly", "pts": best["r"]["pts"]}
        else:
            lo = (min(a["x"], b["x"]) - 160 if f["horiz"] else min(a["y"], b["y"]) - 160)
            hi = (max(a["x"] + a["w"], b["x"] + b["w"]) + 160 if f["horiz"]
                  else max(a["y"] + a["h"], b["y"] + b["h"]) + 160)
            r = None
            for lane in gap_sweep(lo, hi):
                cand = {"es": f["es"], "en": f["en"],
                        "kind": "Zx" if f["horiz"] else "Zy", "lane": lane}
                if clear_w(a, b, cand, frac[i]["s"], frac[i]["t"], ex):
                    r = cand
                    break
            routes[i] = r or {"es": f["es"], "en": f["en"],
                              "kind": "Zx" if f["horiz"] else "Zy",
                              "lane": _r((a["x"] + a["w"] + b["x"]) / 2 if f["horiz"]
                                         else (a["y"] + a["h"] + b["y"]) / 2)}
        reg(geom(a, b, routes[i], frac[i]["s"], frac[i]["t"]))
        take_port(e["src"], routes[i]["es"], frac[i]["s"])
        take_port(e["tgt"], routes[i]["en"], frac[i]["t"])

    # C. NUDGE
    SEP = 16
    paths = []
    for i, r in enumerate(routes):
        if not r or r.get("raw") or specs[i]["opts"].get("route") or specs[i]["opts"].get("style"):
            paths.append(None)
            continue
        g = geom(R(specs[i]["src"]), R(specs[i]["tgt"]), r, frac[i]["s"], frac[i]["t"])
        paths.append([g["sp"], *[{"x": p["x"], "y": p["y"]} for p in g["wp"]], g["ep"]])

    def conflict(s, t):
        return (s["o"] == t["o"] and abs(s["pos"] - t["pos"]) < SEP
                and min(s["hi"], t["hi"]) - max(s["lo"], t["lo"]) > 8)

    for _pass in range(3):
        nseg = []
        for i, P in enumerate(paths):
            if not P:
                continue
            for k in range(1, len(P) - 2):
                p, q = P[k], P[k + 1]
                if abs(p["x"] - q["x"]) < 1 and abs(p["y"] - q["y"]) >= 1:
                    nseg.append({"i": i, "o": "v", "a": P[k], "b": P[k + 1], "pos": p["x"],
                                 "lo": min(p["y"], q["y"]), "hi": max(p["y"], q["y"]),
                                 "tie": P[k - 1]["x"] + P[k + 2]["x"]})
                elif abs(p["y"] - q["y"]) < 1 and abs(p["x"] - q["x"]) >= 1:
                    nseg.append({"i": i, "o": "h", "a": P[k], "b": P[k + 1], "pos": p["y"],
                                 "lo": min(p["x"], q["x"]), "hi": max(p["x"], q["x"]),
                                 "tie": P[k - 1]["y"] + P[k + 2]["y"]})
        comp = [-1] * len(nseg)
        nc = 0
        for x in range(len(nseg)):
            if comp[x] == -1:
                comp[x] = nc
                nc += 1
            for y in range(x + 1, len(nseg)):
                if conflict(nseg[x], nseg[y]):
                    if comp[y] == -1:
                        comp[y] = comp[x]
                    elif comp[y] != comp[x]:
                        frm, to = comp[y], comp[x]
                        for z in range(len(nseg)):
                            if comp[z] == frm:
                                comp[z] = to
        bundles = {}
        for idx_s, s in enumerate(nseg):
            bundles.setdefault(comp[idx_s], []).append(s)
        moved = 0
        for g in bundles.values():
            if len(g) < 2:
                continue
            g.sort(key=lambda A: (A["pos"], A["tie"]))
            center = sum(x["pos"] for x in g) / len(g)
            for j, s in enumerate(g):
                target = _r(center + (j - (len(g) - 1) / 2) * SEP)
                if target == s["pos"]:
                    continue
                old = s["pos"]
                P = paths[s["i"]]
                a, b = R(specs[s["i"]]["src"]), R(specs[s["i"]]["tgt"])
                ex = {specs[s["i"]]["src"], specs[s["i"]]["tgt"]}
                along_before = path_along(P, a, b)
                if s["o"] == "v":
                    s["a"]["x"] = target
                    s["b"]["x"] = target
                else:
                    s["a"]["y"] = target
                    s["b"]["y"] = target
                if path_hit(P, ex) or (not along_before and path_along(P, a, b)):
                    if s["o"] == "v":
                        s["a"]["x"] = old
                        s["b"]["x"] = old
                    else:
                        s["a"]["y"] = old
                        s["b"]["y"] = old
                else:
                    s["pos"] = target
                    moved += 1
        if not moved:
            break

    # re-emit nudged paths as explicit polylines (drop collinear/duplicate)
    for i, P in enumerate(paths):
        if not P:
            continue
        out = [P[0]]
        for k in range(1, len(P) - 1):
            p, q, n = out[-1], P[k], P[k + 1]
            if ((abs(p["x"] - q["x"]) < 1 and abs(q["x"] - n["x"]) < 1)
                    or (abs(p["y"] - q["y"]) < 1 and abs(q["y"] - n["y"]) < 1)):
                continue
            if abs(p["x"] - q["x"]) < 1 and abs(p["y"] - q["y"]) < 1:
                continue
            out.append(q)
        out.append(P[-1])
        routes[i] = {"es": routes[i]["es"], "en": routes[i]["en"],
                     "kind": "poly", "pts": out[1:-1]}

    # D. residual crossings + parallel overlaps (verification)
    d._cross = 0
    for i, e in enumerate(specs):
        r = routes[i]
        if r.get("raw"):
            continue
        a, b = R(e["src"]), R(e["tgt"])
        ex = {e["src"], e["tgt"]}
        if not clear_w(a, b, r, frac[i]["s"], frac[i]["t"], ex):
            d._cross += 1
    fin_seg = []
    for P in paths:
        if not P:
            continue
        for k in range(1, len(P) - 2):
            p, q = P[k], P[k + 1]
            if abs(p["x"] - q["x"]) < 1:
                fin_seg.append({"o": "v", "pos": p["x"], "lo": min(p["y"], q["y"]), "hi": max(p["y"], q["y"])})
            elif abs(p["y"] - q["y"]) < 1:
                fin_seg.append({"o": "h", "pos": p["y"], "lo": min(p["x"], q["x"]), "hi": max(p["x"], q["x"])})
    d._overlaps = 0
    for x in range(len(fin_seg)):
        for y in range(x + 1, len(fin_seg)):
            a, b = fin_seg[x], fin_seg[y]
            if a["o"] == b["o"] and abs(a["pos"] - b["pos"]) < 6 and min(a["hi"], b["hi"]) - max(a["lo"], b["lo"]) > 14:
                d._overlaps += 1

    for i, e in enumerate(specs):
        _emit_edge(d, e, routes[i], frac[i], geom)


def _path_mid(pts: list[dict]) -> dict:
    """Point halfway along a polyline's length — where draw.io anchors a
    relative edge label (x=0) before any offset is applied."""
    segs = list(zip(pts[:-1], pts[1:]))
    total = sum(abs(b["x"] - a["x"]) + abs(b["y"] - a["y"]) for a, b in segs)
    if total <= 0:
        return dict(pts[0])
    half = total / 2
    for a, b in segs:
        seg = abs(b["x"] - a["x"]) + abs(b["y"] - a["y"])
        if half <= seg and seg:
            f = half / seg
            return {"x": a["x"] + (b["x"] - a["x"]) * f,
                    "y": a["y"] + (b["y"] - a["y"]) * f}
        half -= seg
    return dict(pts[-1])


def _solve_label_offset(d, label: str, pts: list[dict],
                        want: tuple | None) -> tuple[float, float] | None:
    """Collision-aware edge-label placement, run AFTER routing so the anchor
    (the actual polyline midpoint) is known. Tries the caller's preferred
    offset first, then a bounded candidate ring; a position must clear every
    obstacle card AND every label already placed this build (label-on-label
    overprint reads as garbage text in the export)."""
    mid = _path_mid(pts)
    lw = max(30.0, len(label) * 6.6)
    lh = 16.0
    boxes = getattr(d, "_label_boxes", None)
    if boxes is None:
        boxes = d._label_boxes = []
    obstacles = [r for r in d.R.values() if r.get("ob")]

    def _overlap(dx: float, dy: float) -> float:
        """Total intersection area with obstacle cards and placed labels."""
        x0, y0 = mid["x"] + dx - lw / 2, mid["y"] + dy - lh / 2
        area = 0.0
        for rr in obstacles:
            area += (max(0.0, min(x0 + lw, rr["x"] + rr["w"]) - max(x0, rr["x"]))
                     * max(0.0, min(y0 + lh, rr["y"] + rr["h"]) - max(y0, rr["y"])))
        for bx, by, bw, bh in boxes:
            area += (max(0.0, min(x0 + lw, bx + bw) - max(x0, bx))
                     * max(0.0, min(y0 + lh, by + bh) - max(y0, by)))
        return area

    cands: list[tuple[float, float]] = []
    if want:
        cands.append((float(want[0]), float(want[1])))
    cands += [(0, 0), (0, -22), (0, 22), (-52, 0), (52, 0), (0, -44), (0, 44),
              (-88, 0), (88, 0), (-52, -22), (52, -22), (-52, 22), (52, 22),
              (-88, -22), (88, -22), (-124, 0), (124, 0)]
    chosen = None
    for c in cands:
        if _overlap(*c) == 0.0:
            chosen = c
            break
    if chosen is None:
        # Nothing fully clears — take the least-bad position instead of piling
        # onto the raw midpoint (a garbled overprint is the worst outcome).
        chosen = min(cands, key=lambda c: _overlap(*c))
    boxes.append((mid["x"] + chosen[0] - lw / 2,
                  mid["y"] + chosen[1] - lh / 2, lw, lh))
    return chosen if chosen != (0.0, 0.0) else None


def _emit_edge(d, e, r, fr, geom) -> None:
    opts = e["opts"]
    label = e.get("label", "")
    dash = opts.get("dash", False)
    flow = opts.get("flow", False)
    rounded = opts.get("rounded", False)
    stroke = opts.get("stroke") or opts.get("color") or THEME.edge_stroke
    # `style` marks a RAW edge (no routing at all); `style_extra` appends class
    # styling AFTER the routed base style, so refined edges get real A*/NUDGE
    # routing + ports + waypoints while keeping their typographic edge classes
    # (later mxGraph keys win, so extra strokeWidth/font overrides are safe).
    raw_style = opts.get("style", "") or opts.get("style_extra", "")
    st = (f"edgeStyle=orthogonalEdgeStyle;html=1;rounded={1 if rounded else 0};"
          f"jettySize=auto;orthogonalLoop=1;fontSize=10;fontColor={THEME.edge_font_color};"
          f"strokeColor={stroke};strokeWidth={THEME.edge_stroke_width};")
    if dash:
        st += "dashed=1;"
    if flow:
        st += "flowAnimation=1;"
    if label:
        st += f"labelBackgroundColor={THEME.edge_label_bg};"
    wp_xml = ""
    label_offset = opts.get("label_offset")
    if r and not r.get("raw"):
        a, b = d.R[e["src"]], d.R[e["tgt"]]
        g = geom(a, b, r, fr["s"], fr["t"])
        if label:
            # Post-routing label solve: the polyline is now known, so place
            # the label where it clears cards and other labels.
            label_offset = _solve_label_offset(
                d, label, [g["sp"], *g["wp"], g["ep"]], label_offset)

        def port(s, f):
            if s == "L":
                return {"x": 0, "y": f}
            if s == "R":
                return {"x": 1, "y": f}
            if s == "T":
                return {"x": f, "y": 0}
            return {"x": f, "y": 1}

        ps, pe = port(r["es"], fr["s"]), port(r["en"], fr["t"])
        st += (f"exitX={ps['x']};exitY={round(ps['y'], 3)};exitDx=0;exitDy=0;"
               f"entryX={pe['x']};entryY={round(pe['y'], 3)};entryDx=0;entryDy=0;")
        bake = d.contract == "bake"
        if bake and g["wp"]:
            pts = "".join(f'<mxPoint x="{_r(q["x"])}" y="{_r(q["y"])}"/>' for q in g["wp"])
            wp_xml = f'<Array as="points">{pts}</Array>'
    if raw_style:
        st += raw_style if raw_style.endswith(";") else raw_style + ";"
    off_xml = ""
    if label and label_offset:
        # Nudges WHERE THE LABEL RENDERS off the line/midpoint (drawio's native
        # edge-label offset point) without touching the routed polyline itself —
        # used by the refined preset to keep labels out of adjacent cards.
        off_xml = f'<mxPoint x="{_r(label_offset[0])}" y="{_r(label_offset[1])}" as="offset"/>'
    d.eid += 1
    # Semantic edge id (refined preset: e_<src>_<tgt>, playbook §18.3) when the
    # caller supplies one and it is still free; ed{n} otherwise.
    eid = opts.get("id") or f"ed{d.eid}"
    if eid != f"ed{d.eid}" and eid in d._cell_index:
        eid = f"ed{d.eid}"
    # Z_EDGE tag => to_xml() sorts connectors behind card shadows/bodies (V2 §7.2).
    from .builder import Z_EDGE
    d._emit_cell(
        eid,
        f'<mxCell id="{eid}" value="{_esc(label)}" style="{st}" edge="1" parent="1" '
        f'source="{e["src"]}" target="{e["tgt"]}"><mxGeometry relative="1" as="geometry">'
        f'{wp_xml}{off_xml}</mxGeometry></mxCell>',
        Z_EDGE)
