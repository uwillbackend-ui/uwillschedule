from src.data_loader import DataLoader
from ortools.sat.python import cp_model

loader = DataLoader("data")
# Disambiguate BRIGHT
# Let us update loader logic for BRIGHT batches:
loader.load_all()

# Group requirements by center
centers = sorted(list({req.center for req in loader.subject_requirements}))

for c in centers:
    model = cp_model.CpModel()
    c_reqs = [r for r in loader.subject_requirements if r.center == c]
    c_vfs = [vf for vf in loader.fixed_lectures if vf.center == c]
    
    # Check if center by itself is feasible
    # Batches in center
    b_keys = {r.batch for r in c_reqs}
    
    batch_day_intervals = {}
    alt_vars = []
    
    for b in b_keys:
        b_info = loader.batches.get((c, b))
        if not b_info:
            for (bc, bb), info in loader.batches.items():
                if bc == c and (bb in b or b in bb):
                    b_info = info; break
        if not b_info:
            continue
            
        op_days = b_info.operating_days
        es, le = b_info.earliest_start_min, b_info.latest_end_min
        
        # recess
        if b_info.recess_start_min and b_info.recess_end_min:
            rst, ret = b_info.recess_start_min, b_info.recess_end_min
            for d in op_days:
                r_iv = model.NewFixedSizeIntervalVar(rst, ret - rst, f"rec_{b}_{d}")
                batch_day_intervals.setdefault((b, d), []).append(r_iv)
                
        # fixed vf
        for vf in c_vfs:
            if vf.batch == b or vf.batch in b or b in vf.batch:
                vf_iv = model.NewFixedSizeIntervalVar(vf.start_min, vf.end_min - vf.start_min, f"vf_{b}_{vf.day}_{vf.start_min}")
                batch_day_intervals.setdefault((b, vf.day), []).append(vf_iv)
                
        # regular reqs
        b_subjs = [r for r in c_reqs if r.batch == b]
        for req in b_subjs:
            w_days = min(req.weekly_days, len(op_days))
            nom_dur = req.daily_duration_min
            dur_options = [nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
            dur_options = [d for d in dur_options if d >= 40]
            
            for inst in range(w_days):
                day_vars = {d: model.NewBoolVar(f"d_{req.req_id}_{inst}_{d}") for d in op_days}
                model.Add(sum(day_vars.values()) == 1)
                
                st_var = model.NewIntVar(es, le - min(dur_options), f"st_{req.req_id}_{inst}")
                dur_var = model.NewIntVarFromDomain(cp_model.Domain.FromValues(dur_options), f"dur_{req.req_id}_{inst}")
                end_var = model.NewIntVar(es + min(dur_options), le, f"end_{req.req_id}_{inst}")
                model.Add(end_var == st_var + dur_var)
                
                alt = model.NewBoolVar(f"alt_{req.req_id}_{inst}")
                model.Add(dur_var != nom_dur).OnlyEnforceIf(alt)
                model.Add(dur_var == nom_dur).OnlyEnforceIf(alt.Not())
                alt_vars.append(alt)
                
                for d in op_days:
                    iv = model.NewOptionalIntervalVar(st_var, dur_var, end_var, day_vars[d], f"iv_{req.req_id}_{inst}_{d}")
                    batch_day_intervals.setdefault((b, d), []).append(iv)
                    
            # at most 1 lecture per subject per day in batch
            for d in op_days:
                # find all inst of this req on day d
                # model.Add(...)
                pass
                
        # max 20% altered
        if alt_vars:
            model.Add(sum(alt_vars) <= int(0.20 * len(alt_vars)))
            
    for (b, d), ivs in batch_day_intervals.items():
        model.AddNoOverlap(ivs)
        
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    st = solver.Solve(model)
    status_name = solver.StatusName(st)
    print(f"Center {c:10s}: {status_name} (Batches: {len(b_keys)}, Reqs: {len(c_reqs)}, VFs: {len(c_vfs)})")
