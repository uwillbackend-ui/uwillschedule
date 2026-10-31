import sys, os
sys.path.insert(0, os.path.abspath("."))
import time
from src.data_loader import DataLoader, parse_time_to_minutes, minutes_to_str, DAYS_OF_WEEK
from src.models import ScheduledSlot
from scripts.enforce_zero_deficits import enforce_zero_deficits

loader = DataLoader("data")
loader.load_all()

# We can test with generate_timetable.py
import generate_timetable

print("Starting generation test...")
generate_timetable.run_schedule_generation()
