import sys, os, re
sys.path.insert(0, os.path.abspath("."))
from ortools.sat.python import cp_model

with open("generate_timetable.py") as f:
    orig_code = f.read()

def test_code(code_str, label):
    print(f"\n--- TESTING: {label} ---")
    g = {}
    # remove the run_schedule_generation() call at bottom
    c = code_str.replace('if __name__ == "__main__":\n    run_schedule_generation()', '')
    exec(c, g)
    # now run run_schedule_generation but with short solver time limit
    # We can patch cp_model.CpSolver
    old_init = cp_model.CpSolver.__init__
    def new_init(self):
        old_init(self)
        self.parameters.max_time_in_seconds = 10.0
        self.parameters.log_search_progress = False
    cp_model.CpSolver.__init__ = new_init
    
    try:
        g['run_schedule_generation']()
    except Exception as e:
        print(f"Exception: {e}")
    finally:
        cp_model.CpSolver.__init__ = old_init

# Test 1: Current code as is
test_code(orig_code, "Current code")

# Test 2: Without day_vars['FRIDAY'] == 0 for BRIGHT Section B
code2 = orig_code.replace('if c == "BRIGHT" and b == "11TH CBSE - B":\n                    model.Add(day_vars["FRIDAY"] == 0)', '# no friday constraint')
test_code(code2, "Without Friday == 0 constraint")

# Test 3: Without explicit test placement for BRIGHT Section B
code3 = code2.replace('if c == "BRIGHT" and b == "11TH CBSE - B":\n            model.Add(t1_day_vars["MONDAY"] == 1)', 'if False and c == "BRIGHT":\n            pass')
test_code(code3, "Without explicit test placement")

# Test 4: Without Suketu Sir BRIGHT affinity
code4 = code3.replace('elif c == "BRIGHT" and "B" in b:', 'elif False:')
test_code(code4, "Without Suketu Sir BRIGHT affinity")

# Test 5: Without Darshan Sir BRIGHT affinity
code5 = code4.replace('if is_3day and fac_up == "DARSHAN SIR":', 'if False:')
test_code(code5, "Without Darshan Sir BRIGHT affinity")

# Test 6: Without Saturday cutoff removal (revert day_le to max_batch_le)
code6 = code5.replace('day_le = max_batch_le if (c == "JAI AMBE") else b_info.day_latest_end.get(d, le)', 'day_le = max_batch_le if (c == "BRIGHT" and d == "SATURDAY") or (c == "JAI AMBE") else b_info.day_latest_end.get(d, le)')
test_code(code6, "Without Saturday cutoff (old override)")

# Test 7: Without 50m minimum (old 45m)
code7 = code6.replace('50 <= d <= 120', '45 <= d <= 120')
test_code(code7, "Old 45m min")
