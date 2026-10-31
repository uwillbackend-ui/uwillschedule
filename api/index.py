import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from web_app import SchedulerRequestHandler

class handler(SchedulerRequestHandler):
    pass
