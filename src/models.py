from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set

@dataclass
class BatchInfo:
    center: str
    name: str
    earliest_start_min: int  # minutes from midnight (e.g. 480 for 8:00 AM)
    latest_end_min: int      # minutes from midnight (e.g. 780 for 1:00 PM)
    operating_days: List[str] # ["MONDAY", "TUESDAY", ...]
    start_mode: str          # "Fixed" or "Flexible"
    end_mode: str            # "Fixed" or "Flexible"
    recess_start_min: Optional[int] = None
    recess_end_min: Optional[int] = None
    recess_earliest_start_min: Optional[int] = None
    recess_latest_end_min: Optional[int] = None
    recess_duration_min: Optional[int] = None
    recess_mode: str = "Fixed"
    day_earliest_start: Dict[str, int] = field(default_factory=dict)
    day_latest_end: Dict[str, int] = field(default_factory=dict)

@dataclass
class FacultyRestrictions:
    name: str
    # Per day: (morning_from, morning_to, evening_from, evening_to) in minutes
    day_limits: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)
    max_weekly_hours: float = 40.0
    available_from_min: Optional[int] = None
    available_to_min: Optional[int] = None

@dataclass
class SubjectRequirement:
    req_id: str
    center: str
    batch: str
    subject: str
    faculty: str
    daily_duration_min: int   # nominal duration, e.g. 60 or 75 mins
    weekly_hours: float
    weekly_days: int          # number of distinct days per week
    allow_duration_flex: bool = True

@dataclass
class FixedLecture:
    center: str
    batch: str
    day: str
    start_min: int
    end_min: int
    subject: str
    faculty: str

@dataclass(unsafe_hash=True)
class ScheduledSlot:
    batch_key: str
    center: str
    batch_name: str
    day: str
    start_min: int
    end_min: int
    subject: str
    faculty: str
    is_fixed: bool = False
    chapter: str = ""
    topic: str = ""

    @property
    def duration_min(self) -> int:
        return self.end_min - self.start_min
