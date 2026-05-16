"""
Parse validation output files and compute:
  - Pass/fail rates per metric (bnd, wkt, eco, dot)
  - Mean signed error and direction (simulator bias)
  - Variance of each metric per entity, using binomial SE for rates
"""
import re, math, sys
from collections import defaultdict

FILES = {
    "T20":  "validation_results/20260516_145126/T20.txt",
    "ODI":  "validation_results/20260516_145126/ODI.txt",
    "Test": "validation_results/20260516_145126/Test.txt",
}

# Regex patterns
PHASE_RE = re.compile(
    r"^\s+(\w+)\s+n=\s*([\d,]+)/([\d,]+)\s+"
    r"bnd ([\d.]+)/([\d.]+)([✓✗])\s+"
    r"wkt ([\d.]+)/([\d.]+)([✓✗])\s+"
    r"eco ([\d.]+)/([\d.]+)([✓✗])\s+"
    r"dot ([\d.]+)/([\d.]+)([✓✗])"
)
SCORE_RE = re.compile(r"^\s+score_avg\s+sim=([\d.]+)\s+hist=([\d.]+)\s+([✓✗])")
ENTITY_RE = re.compile(r"^\s{2}(\S.+?)\s{2,}")  # entity header lines

def parse_int(s):
    return int(s.replace(",", ""))

def binomial_se(p, n):
    if n == 0 or p < 0 or p > 1:
        return 0.0
    return math.sqrt(p * (1 - p) / n)

def run():
    # Global accumulators
    metric_stats = defaultdict(lambda: {
        "pass": 0, "fail": 0,
        "errors": [],          # signed: sim - hist
        "rel_errors": [],      # (sim-hist)/hist
    })
    # Per phase-type breakdowns
    phase_stats = defaultdict(lambda: defaultdict(lambda: {
        "pass": 0, "fail": 0, "errors": []
    }))
    # Per entity: collect metric values + SE to compute inter-phase variance
    entity_records = []

    for fmt, fpath in FILES.items():
        with open(fpath) as f:
            lines = f.readlines()

        current_entity = None
        entity_type = None   # VENUE, BATTER, BOWLER
        entity_phases = []

        def flush_entity():
            if current_entity and entity_phases:
                entity_records.append({
                    "fmt": fmt,
                    "type": entity_type,
                    "name": current_entity,
                    "phases": entity_phases[:],
                })

        for line in lines:
            # Detect section headers
            if "VENUE RESULTS" in line:
                flush_entity(); current_entity = None; entity_type = "venue"
            elif "BATTER RESULTS" in line:
                flush_entity(); current_entity = None; entity_type = "batter"
            elif "BOWLER RESULTS" in line:
                flush_entity(); current_entity = None; entity_type = "bowler"

            # Score avg
            m = SCORE_RE.match(line)
            if m:
                sim_s, hist_s, ok = float(m.group(1)), float(m.group(2)), m.group(3)
                err = sim_s - hist_s
                k = f"score_avg"
                metric_stats[k]["errors"].append(err)
                metric_stats[k]["rel_errors"].append(err / hist_s if hist_s else 0)
                if ok == "✓":
                    metric_stats[k]["pass"] += 1
                else:
                    metric_stats[k]["fail"] += 1
                continue

            # Phase row
            m = PHASE_RE.match(line)
            if m:
                phase = m.group(1)
                n_sim = parse_int(m.group(2))
                n_hist = parse_int(m.group(3))
                bnd_s, bnd_h, bnd_ok = float(m.group(4)), float(m.group(5)), m.group(6)
                wkt_s, wkt_h, wkt_ok = float(m.group(7)), float(m.group(8)), m.group(9)
                eco_s, eco_h, eco_ok = float(m.group(10)), float(m.group(11)), m.group(12)
                dot_s, dot_h, dot_ok = float(m.group(13)), float(m.group(14)), m.group(15)

                for metric, sim_v, hist_v, ok in [
                    ("bnd", bnd_s, bnd_h, bnd_ok),
                    ("wkt", wkt_s, wkt_h, wkt_ok),
                    ("eco", eco_s, eco_h, eco_ok),
                    ("dot", dot_s, dot_h, dot_ok),
                ]:
                    err = sim_v - hist_v
                    rel_err = err / hist_v if hist_v else 0
                    key = metric
                    metric_stats[key]["errors"].append(err)
                    metric_stats[key]["rel_errors"].append(rel_err)
                    if ok == "✓":
                        metric_stats[key]["pass"] += 1
                        phase_stats[phase][metric]["pass"] += 1
                    else:
                        metric_stats[key]["fail"] += 1
                        phase_stats[phase][metric]["fail"] += 1
                    phase_stats[phase][metric]["errors"].append(err)

                    # Also breakdown by entity type
                    if entity_type:
                        ek = f"{metric}_{entity_type}"
                        metric_stats[ek]["errors"].append(err)
                        metric_stats[ek]["rel_errors"].append(rel_err)
                        if ok == "✓":
                            metric_stats[ek]["pass"] += 1
                        else:
                            metric_stats[ek]["fail"] += 1

                entity_phases.append({
                    "phase": phase,
                    "n_sim": n_sim,
                    "n_hist": n_hist,
                    "bnd": (bnd_s, bnd_h, bnd_ok),
                    "wkt": (wkt_s, wkt_h, wkt_ok),
                    "eco": (eco_s, eco_h, eco_ok),
                    "dot": (dot_s, dot_h, dot_ok),
                })
                continue

            # Detect entity header (2-space indent, not a phase/score line)
            stripped = line.rstrip()
            if stripped and stripped.startswith("  ") and not stripped.startswith("   ") \
               and not stripped.startswith("  [") and not stripped.startswith("  Pre") \
               and not stripped.startswith("  Ini") and not stripped.startswith("  Venue") \
               and not stripped.startswith("  Batter") and not stripped.startswith("  Bowler") \
               and not stripped.startswith("  ─") and not stripped.startswith("  Target") \
               and not stripped.startswith("  Results") and "hist_deliveries" not in stripped \
               and "hist_balls" not in stripped and "career_balls" not in stripped \
               and "sim_matches" not in stripped and "670 " not in stripped \
               and "407 " not in stripped and "230 " not in stripped:
                # Likely a new entity name in the section description line,
                # but entity header comes just before phase lines
                pass

            # Detect actual entity header lines (have parenthetical country info OR pos_group OR type=)
            if re.search(r"hist_deliveries=|hist_balls=|career_balls=", stripped):
                flush_entity()
                # Extract name: everything before the first triple-space or paren
                name_match = re.match(r"\s{2}(.+?)\s{2,}", stripped)
                current_entity = name_match.group(1).strip() if name_match else stripped.strip()
                entity_phases = []

        flush_entity()

    # ── REPORT ──────────────────────────────────────────────────────────────
    def stats(vals):
        if not vals:
            return 0, 0, 0
        mean = sum(vals) / len(vals)
        variance = sum((v - mean)**2 for v in vals) / len(vals)
        sd = math.sqrt(variance)
        return mean, sd, len(vals)

    metrics = ["bnd", "wkt", "eco", "dot"]

    print("\n" + "═"*80)
    print("  METRIC-LEVEL PASS RATES AND BIAS")
    print("═"*80)
    print(f"  {'Metric':<10}  {'Pass%':>6}  {'N':>5}  {'MeanErr':>8}  {'SD_err':>8}  {'Direction'}")
    print(f"  {'-'*10}  {'-'*6}  {'-'*5}  {'-'*8}  {'-'*8}  {'-'*20}")
    for m in metrics + ["eco", "score_avg"]:
        if m == "eco" and m in metrics:
            continue  # already printed
        s = metric_stats[m]
        total = s["pass"] + s["fail"]
        pct = 100 * s["pass"] / total if total else 0
        mean_e, sd_e, n = stats(s["errors"])
        direction = "OVER" if mean_e > 0 else "under"
        print(f"  {m:<10}  {pct:>5.1f}%  {total:>5}  {mean_e:>+8.4f}  {sd_e:>8.4f}  {direction}")

    print()
    print("  (Eco is runs-per-over: positive error = simulator too aggressive)")
    print()

    # ── PASS RATES BY METRIC × ENTITY TYPE ──
    print("═"*80)
    print("  PASS RATE BY METRIC × ENTITY TYPE")
    print("═"*80)
    print(f"  {'':12}  {'bnd':>6}  {'wkt':>6}  {'eco':>6}  {'dot':>6}")
    print(f"  {'-'*12}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}")
    for etype in ["venue", "batter", "bowler"]:
        row = f"  {etype:<12}"
        for m in metrics:
            s = metric_stats[f"{m}_{etype}"]
            total = s["pass"] + s["fail"]
            pct = 100 * s["pass"] / total if total else 0
            row += f"  {pct:>5.1f}%"
        print(row)
    print()

    # ── BIAS DIRECTION BY METRIC × ENTITY TYPE ──
    print("═"*80)
    print("  MEAN SIGNED ERROR BY METRIC × ENTITY TYPE  (positive = sim too high)")
    print("═"*80)
    print(f"  {'':12}  {'bnd':>8}  {'wkt':>8}  {'eco':>8}  {'dot':>8}")
    print(f"  {'-'*12}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}")
    for etype in ["venue", "batter", "bowler"]:
        row = f"  {etype:<12}"
        for m in metrics:
            s = metric_stats[f"{m}_{etype}"]
            mean_e, sd_e, n = stats(s["errors"])
            row += f"  {mean_e:>+8.4f}"
        print(row)
    print()

    # ── PASS RATES BY GAME PHASE ──
    print("═"*80)
    print("  PASS RATE BY PHASE")
    print("═"*80)
    print(f"  {'Phase':<12}  {'bnd':>6}  {'wkt':>6}  {'eco':>6}  {'dot':>6}  {'N_obs':>6}")
    print(f"  {'-'*12}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}")
    phase_order = ["new", "pp1", "pp2", "early", "mid1", "mid2", "mid3", "middle", "death1", "death2", "late"]
    for phase in phase_order:
        if phase not in phase_stats:
            continue
        row = f"  {phase:<12}"
        n_obs = 0
        for m in metrics:
            s = phase_stats[phase][m]
            total = s["pass"] + s["fail"]
            pct = 100 * s["pass"] / total if total else 0
            row += f"  {pct:>5.1f}%"
            n_obs = total
        row += f"  {n_obs:>6}"
        print(row)
    print()

    # ── BIAS DIRECTION BY PHASE ──
    print("═"*80)
    print("  MEAN SIGNED ERROR BY PHASE  (positive = sim overshoots)")
    print("═"*80)
    print(f"  {'Phase':<12}  {'bnd':>8}  {'wkt':>8}  {'eco':>8}  {'dot':>8}")
    print(f"  {'-'*12}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}")
    for phase in phase_order:
        if phase not in phase_stats:
            continue
        row = f"  {phase:<12}"
        for m in metrics:
            s = phase_stats[phase][m]
            mean_e, sd_e, n = stats(s["errors"])
            row += f"  {mean_e:>+8.4f}"
        print(row)
    print()

    # ── PER-ENTITY VARIANCE (inter-phase spread) ──
    print("═"*80)
    print("  PER-ENTITY INTER-PHASE VARIANCE  (how spread out sim vs hist is across phases)")
    print("  Higher variance = inconsistent: some phases right, others badly wrong")
    print("═"*80)
    print(f"  {'Entity':<35}  {'Type':<7}  {'Fmt':<5}  {'bnd_sd':>7}  {'wkt_sd':>7}  {'eco_sd':>7}  {'dot_sd':>7}  {'n_phases':>8}")
    print(f"  {'-'*35}  {'-'*7}  {'-'*5}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*8}")

    entity_variance_rows = []
    for ent in entity_records:
        row_metrics = {}
        for m in metrics:
            idx = {"bnd": 0, "wkt": 1, "eco": 2, "dot": 3}[m]
            errs = [p[m][0] - p[m][1] for p in ent["phases"]]
            _, sd, n = stats(errs)
            row_metrics[m] = sd
        entity_variance_rows.append((ent, row_metrics))

    # Sort by average SD descending (most variable entities first)
    entity_variance_rows.sort(key=lambda x: sum(x[1].values()), reverse=True)

    for ent, rm in entity_variance_rows[:30]:
        name = ent["name"][:35]
        n_phases = len(ent["phases"])
        row = (f"  {name:<35}  {ent['type']:<7}  {ent['fmt']:<5}"
               f"  {rm['bnd']:>7.4f}  {rm['wkt']:>7.4f}  {rm['eco']:>7.4f}  {rm['dot']:>7.4f}  {n_phases:>8}")
        print(row)
    print()

    # ── WORST INDIVIDUAL PHASE ERRORS ──
    print("═"*80)
    print("  TOP 20 WORST INDIVIDUAL PHASE ERRORS (by relative error)")
    print("═"*80)
    print(f"  {'Entity':<30}  {'Phase':<8}  {'Metric':<6}  {'Sim':>6}  {'Hist':>6}  {'Err%':>7}  {'SE_hist':>8}  {'Sigmas':>7}")
    print(f"  {'-'*30}  {'-'*8}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*7}  {'-'*8}  {'-'*7}")

    worst = []
    for ent in entity_records:
        for p in ent["phases"]:
            for m in metrics:
                sim_v, hist_v, ok = p[m]
                if hist_v == 0:
                    continue
                err = sim_v - hist_v
                rel_err = abs(err / hist_v)
                # Use hist n to compute SE; n_hist is in phase record
                n_hist = p.get("n_hist", p.get("n_sim", 100))
                # For rates (bnd/wkt/dot), use binomial SE; for eco scale differently
                if m in ("bnd", "wkt", "dot"):
                    se = binomial_se(hist_v, n_hist)
                else:
                    # economy: treat as rate * 6, rough SE
                    rate = hist_v / 6.0
                    se = binomial_se(min(rate, 1.0), n_hist) * 6
                sigmas = abs(err) / se if se > 0 else 0
                worst.append((ent["name"][:30], p["phase"], m, sim_v, hist_v, err, rel_err, se, sigmas, ok))

    worst.sort(key=lambda x: x[6], reverse=True)
    for name, phase, m, sim_v, hist_v, err, rel_err, se, sigmas, ok in worst[:20]:
        print(f"  {name:<30}  {phase:<8}  {m:<6}  {sim_v:>6.3f}  {hist_v:>6.3f}  {err/hist_v*100:>+6.1f}%  {se:>8.4f}  {sigmas:>7.1f}σ  {'✗' if ok=='✗' else '✓'}")
    print()

    # ── ODI SCORE BIAS (summary) ──
    print("═"*80)
    print("  SCORE AVERAGE ERRORS (score_avg sim vs hist)")
    print("═"*80)
    for m in ["score_avg"]:
        s = metric_stats[m]
        mean_e, sd_e, n = stats(s["errors"])
        total = s["pass"] + s["fail"]
        pct = 100 * s["pass"] / total if total else 0
        print(f"  Pass rate: {pct:.0f}%   Mean error: {mean_e:+.1f} runs   SD: {sd_e:.1f} runs   N={n}")
        pos = sum(1 for e in s["errors"] if e > 0)
        print(f"  Overpredicted: {pos}/{n} venues ({100*pos/n:.0f}%)  Underpredicted: {n-pos}/{n} venues ({100*(n-pos)/n:.0f}%)")
    print()

if __name__ == "__main__":
    run()
