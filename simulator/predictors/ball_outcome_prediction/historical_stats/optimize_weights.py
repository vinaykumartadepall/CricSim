import os
import sys
import random
import math
from collections import defaultdict

sys.path.append(os.getcwd())

from db.database import get_db_connection
from simulator.predictors.ball_outcome_prediction.historical_stats.strategy import compute_context_multiplier
from db.stats_repository import StatsRepository

# Parameters to search:
# w_bat, w_bowl, w_over, w_venue, w_inn, w_tourn

def load_data(match_format='T20', gender='male', sample_size=15000):
    conn = get_db_connection()
    cur = conn.cursor()
    print(f"Fetching {sample_size} random deliveries for {match_format} ({gender})...")
    
    query = """
        SELECT 
            d.batter_id, d.bowler_id, m.venue_id, d.inning_number, d.over_number, m.tournament_id,
            d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind
        FROM history.deliveries d
        JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.match_format = ANY(%s) AND m.gender = %s
        ORDER BY RANDOM()
        LIMIT %s
    """
    cur.execute(query, (['T20', 'IT20'] if match_format=='T20' else [match_format], gender, sample_size))
    rows = cur.fetchall()
    
    # Collect IDs for caches
    batter_ids = list(set([r[0] for r in rows]))
    bowler_ids = list(set([r[1] for r in rows]))
    venue_ids = list(set([r[2] for r in rows]))
    tourn_ids = list(set([r[5] for r in rows]))
    
    print("Loading caches from DB...")
    repo = StatsRepository()
    
    baseline_cache = repo.get_innings_distribution(match_format, gender)
    combined_base = {}
    for inn_num, metrics in baseline_cache.items():
        for k, prob in metrics.items():
            combined_base[k] = combined_base.get(k, 0) + prob
            
    num_innings = len(baseline_cache) if len(baseline_cache) > 0 else 1
    for k in combined_base:
        combined_base[k] /= num_innings
        
    tot = sum(combined_base.values())
    baseline_probs = {k: v/tot for k,v in combined_base.items()} if tot > 0 else {}
    ordered_keys = list(baseline_probs.keys())
    
    batter_cache = repo.get_batters_distribution(batter_ids, match_format, gender)
    bowler_cache = repo.get_bowlers_distribution(bowler_ids, match_format, gender)
    overs_cache = repo.get_overs_distribution(match_format, gender)
    
    # Venue and Tourn caches (fetching per ID is heavy so we just rely on standard queries)
    # Actually StatsRepository only has get_venue_distribution for single venue. Let's optimize:
    venue_cache = {} # We'll build this via raw query to save time
    cur.execute("""
        SELECT m.venue_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.match_format = ANY(%s) AND m.venue_id = ANY(%s) AND m.gender = %s
        GROUP BY 1, 2, 3, 4, 5
    """, (['T20', 'IT20'] if match_format=='T20' else [match_format], venue_ids, gender))
    v_rows = cur.fetchall()
    v_grouped = defaultdict(list)
    for r in v_rows: v_grouped[r[0]].append(r[1:])
    for v_id, mets in v_grouped.items():
        probs = repo._parse_rows_to_probs(mets)
        if probs: venue_cache[v_id] = probs

    tourn_cache = {}
    cur.execute("""
        SELECT m.tournament_id, d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, COUNT(*)
        FROM history.deliveries d JOIN history.matches m ON d.match_id = m.match_id
        WHERE m.tournament_id = ANY(%s) AND m.gender = %s
        GROUP BY 1, 2, 3, 4, 5
    """, (tourn_ids, gender))
    t_rows = cur.fetchall()
    t_grouped = defaultdict(list)
    for r in t_rows: t_grouped[r[0]].append(r[1:])
    for t_id, mets in t_grouped.items():
        probs = repo._parse_rows_to_probs(mets)
        if probs: tourn_cache[t_id] = probs
        
    cur.close()
    conn.close()

    print("Precomputing ratio matrix for all deliveries...")
    precomputed_data = []
    for row in rows:
        bat_id, bowl_id, ven_id, inn_id, ovr_id, trn_id, r_bat, r_ext, o_typ, o_kind = row
        true_key = (r_bat, r_ext, o_typ, o_kind)
        
        try:
            true_idx = ordered_keys.index(true_key)
        except ValueError:
            continue
            
        bat_p  = batter_cache.get(bat_id, baseline_probs)
        bowl_p = bowler_cache.get(bowl_id, baseline_probs)
        ven_p  = venue_cache.get(ven_id, baseline_probs)
        inn_p  = baseline_cache.get(inn_id, baseline_probs)
        ovr_p  = overs_cache.get(ovr_id, baseline_probs)
        trn_p  = tourn_cache.get(trn_id, baseline_probs)
        
        r_bat_arr, r_bol_arr, r_ven_arr, r_inn_arr, r_ovr_arr, r_trn_arr = [], [], [], [], [], []
        for key in ordered_keys:
            base_p = baseline_probs.get(key, 0.0001)
            def get_capped_ratio(context_p):
                return max(0.1, min(10.0, context_p.get(key, base_p) / base_p))
                
            r_bat_arr.append(get_capped_ratio(bat_p))
            r_bol_arr.append(get_capped_ratio(bowl_p))
            r_ven_arr.append(get_capped_ratio(ven_p))
            r_inn_arr.append(get_capped_ratio(inn_p))
            r_ovr_arr.append(get_capped_ratio(ovr_p))
            r_trn_arr.append(get_capped_ratio(trn_p))
            
        precomputed_data.append((true_idx, r_bat_arr, r_bol_arr, r_ven_arr, r_inn_arr, r_ovr_arr, r_trn_arr))

    return precomputed_data, ordered_keys, baseline_probs


def eval_loss(weights, data_tuple):
    w_bat, w_bowl, w_ven, w_inn, w_ovr, w_trn = weights
    precomputed_data, ordered_keys, baseline_probs = data_tuple
    
    total_log_loss = 0.0
    base_probs = [baseline_probs.get(k, 0.0001) for k in ordered_keys]
    
    def _agg(r):
        return r * (1.2 if r > 1.0 else 0.8)

    for row in precomputed_data:
        true_idx, r_bat, r_bol, r_ven, r_inn, r_ovr, r_trn = row

        combined_weights = [
            base_probs[i]
            * (_agg(r_bat[i]) ** w_bat)
            * (_agg(r_bol[i]) ** w_bowl)
            * (_agg(r_ven[i]) ** w_ven)
            * (_agg(r_inn[i]) ** w_inn)
            * (_agg(r_ovr[i]) ** w_ovr)
            * (_agg(r_trn[i]) ** w_trn)
            for i in range(len(ordered_keys))
        ]
            
        tot_wt = sum(combined_weights)
        if tot_wt <= 0:
            pred = 1.0 / len(ordered_keys)
        else:
            pred = combined_weights[true_idx] / tot_wt
                
        pred = max(1e-6, min(1.0, pred))
        total_log_loss -= math.log(pred)
        
    return total_log_loss / len(precomputed_data)


def optimize(data_tuple, steps=40):
    # Optimize unconstrained logits, map to probabilities via Softmax
    w_logits = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    
    def get_softmax_weights(logits):
        exp_w = [math.exp(lw) for lw in logits]
        sum_exp = sum(exp_w)
        return [ew / sum_exp for ew in exp_w]

    best_loss = eval_loss(get_softmax_weights(w_logits), data_tuple)
    best_logits = w_logits.copy()
    print(f"Initial log loss (uniform distribution): {best_loss:.4f}")

    alpha = 2.5  # Boosted learning rate
    momentum = 0.8
    velocity = [0.0] * 6

    for step in range(steps):
        grad = [0] * 6
        epsilon = 0.01

        for i in range(6):
            w_plus = w_logits.copy()
            w_plus[i] += epsilon
            loss_plus = eval_loss(get_softmax_weights(w_plus), data_tuple)

            w_minus = w_logits.copy()
            w_minus[i] -= epsilon
            loss_minus = eval_loss(get_softmax_weights(w_minus), data_tuple)

            grad[i] = (loss_plus - loss_minus) / (2 * epsilon)

        for i in range(6):
            velocity[i] = momentum * velocity[i] - alpha * grad[i]
            # Simulated annealing noise, decaying over steps
            noise = random.uniform(-0.1, 0.1) * max(0, (steps - step) / steps)
            w_logits[i] += velocity[i] + noise

        current_weights = get_softmax_weights(w_logits)
        current_loss = eval_loss(current_weights, data_tuple)

        if current_loss < best_loss:
            best_loss = current_loss
            best_logits = w_logits.copy()

        print(f"Step {step+1:02d} | Loss: {current_loss:.4f} | Best: {best_loss:.4f} | Weights: {[round(x, 3) for x in current_weights]}")

    return get_softmax_weights(best_logits)


if __name__ == "__main__":
    for fmt in ['T20', 'ODI', 'Test']:
        try:
            data = load_data(fmt, gender='male', sample_size=15000)
            if not data[0]:
                print(f"Skipping {fmt} - No data found in database.")
                continue
            best_w = optimize(data, steps=40)
            print(f"\nFinal learned weights for {fmt}:")
            print(f"w_batter  = {best_w[0]:.3f}")
            print(f"w_bowler  = {best_w[1]:.3f}")
            print(f"w_venue   = {best_w[2]:.3f}")
            print(f"w_innings = {best_w[3]:.3f}")
            print(f"w_over    = {best_w[4]:.3f}")
            print(f"w_tourn   = {best_w[5]:.3f}")
        except Exception as e:
            print(f"Failed to optimize for {fmt}: {e}")
