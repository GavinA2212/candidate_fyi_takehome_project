import random
from datetime import datetime, timedelta, time
from faker import Faker

fake = Faker()
Faker.seed(0)


# --**Updated to generate more complex busy blocks with minute precision, aswell as sorted times for easier displaying**--
def generate_busy_blocks(start_date, days=7):
    busy_blocks = []
    work_hours = (9, 17)  # Work hours from 9 AM to 5 PM
    
    # Generate 3-6 busy blocks
    for _ in range(random.randint(3, 6)):
        day_offset = random.randint(0, days - 1)
        date = start_date + timedelta(days=day_offset)

        # Choose random start time with minute precision (5-minute intervals)
        start_hour = random.randint(work_hours[0], work_hours[1] - 1)
        start_minute = random.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
        
        # Duration between 30 minutes and 2.5 hours (in 5-minute increments)
        # 30 minutes = 6 increments, 2.5 hours = 30 increments
        duration_minutes = random.randint(6, 30) * 5
        
        start_dt = datetime.combine(date, time(start_hour, start_minute)).replace(tzinfo=None)
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        # Ensure end time doesn't exceed work hours
        max_end_time = datetime.combine(date, time(work_hours[1], 0)).replace(tzinfo=None)
        if end_dt > max_end_time:
            end_dt = max_end_time

        busy_blocks.append({
            "start": start_dt.isoformat() + "Z",
            "end": end_dt.isoformat() + "Z",
        })
        busy_blocks.sort(key=lambda x: x["start"])

    return busy_blocks


def get_free_busy_data(interviewer_ids: list[int]) -> list[dict]:
    start_date = datetime.utcnow().date()
    data = []

    for id_ in interviewer_ids:
        interviewer = {
            "interviewerId": id_,
            "name": fake.name(),
            "busy": generate_busy_blocks(start_date)  # Changed from 'availability' to 'busy'
        }
        data.append(interviewer)

    return data 


# ------ Helper functions ------


def calculate_duration_minutes(start_str, end_str):
    """Calculate duration in minutes between two ISO format datetime strings"""
    if start_str.endswith('Z'):
        start_str = start_str[:-1] + '+00:00'
    if end_str.endswith('Z'):
        end_str = end_str[:-1] + '+00:00'
        
    start = datetime.fromisoformat(start_str)
    end = datetime.fromisoformat(end_str)
    
    duration = end - start
    return int(duration.total_seconds() / 60)