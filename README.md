# Candidate.fyi Takehome Project

This repository contains the implementation of the Candidate.fyi Takehome Project, a Django-based API for managing interview templates and scheduling. By Gavin Augsburger.

## Setup Instructions

### Prerequisites
- Docker and Docker Compose
- Make (optional, for using the Makefile commands)

### Set Up

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd candidate_fyi_takehome_project
   ```

2. Start the development environment:
   ```bash
   make up
   ```
   or
   ```bash
   docker-compose -f docker-compose.local.yml up -d
   ```

3. Make and run migrations:
  #1
   ```bash
   make makemigrations
   ```
   or
   ```bash
   docker compose run --rm django python ./manage.py makemigrations
   ```
   #2
   ```bash
   make migrate
   ```
   or
   ```bash
   docker compose run --rm django python ./manage.py migrate
   ```

4. Seed the database with randomly generated initial interviewers and interviewtemplates data:
   ```bash
   make seed
   ```
   or
   ```bash
   docker compose run --rm django python ./manage.py seed_interviews
   ```

5. Access the API at:
   ```
   http://localhost:8000/api/
   ```

6. Test the API endpoint:
   ```
   http://localhost:8000/api/interviews/<int:templateid>/availability/
   ```

   Optional query parameters:
   - `start`: ISO 8601 datetime (default: 24 hours from now) - start of search window
   - `end`: ISO 8601 datetime (default: start + 7 days) - end of search window
   - `start_hour`: Integer hour 0-23 (default: 9) - daily workday start hour constraint 
   - `end_hour`: Integer hour 0-23 (default: 17) - daily workday end hour constraint 


### Running Interview Tests
```bash
make test      # Run interviews app tests
```

## Design Decisions

### Architecture
Initial changes:
The project initially starts with a dependency error upon first attempt at running. This error is fixed by changing django-allauth[mfa] in requirements/base.txt to atleast version 65.8.1, to fix the fido2 dependency error that crashes the django docker container.

I also added watchfiles execution to the local django start file, so that changes would be reflected realtime on docker containers without needing to restart them after making changes

Lastly I changed the generate_busy_blocks function to generate more complex busy blocks with minute precision, aswell as sorted times for easier displaying

Interviews architecture:
I created a interviews django app to store all interview related models, views, urls, serializers and tests, aswell as a seed command to seed interview data

The only view: InterviewAvailabilityView is quite complex, and includes a few helper function to isolate functionality. these helper functions would likely be placed in another location in a real production environment to keep the views file less verbose, but I kept them in the views file for ease of viewing given the nature of the project.


### Data Models
The models for this project are kept simple, only requiring the data that the API needs for the task.

Interviewer: 
id 

InterviewTemplate:
id
name 
duration (in minutes)
interviewers (many to many relationship with Interviewer model)

While these models would likely be expanded upon with a full scale project, other values are not yet needed, so they are kept simple, and with the use of the get_free_busy_data function, we do not need to save the schedules to the database yet since we are just using generated sample data.

### API Design
- /api/interviews/<int:templateid>/availability/

includes the following optional query params for further customized testing and control:
- `start`: ISO 8601 datetime (default: 24 hours from now) - start of search window
- `end`: ISO 8601 datetime (default: start + 7 days) - end of search window
- `start_hour`: Integer hour 0-23 (default: 9) - daily workday start hour constraint 
- `end_hour`: Integer hour 0-23 (default: 17) - daily workday end hour constraint 

Response:

All expected values from the Readme, plus added humanreadable versions of the response that includes the available slots and the busy times in a easier to read format. These values would not be returned in a real production environment, but are purely for showcase of the Endpoint's results.

```json
{
  "interviewId": 1,
  "name": "Technical Interview",
  "durationMinutes": 60,
  "interviewers": [
    { "id": 1, "name": "Alice Johnson" },
    { "id": 2, "name": "Bob Smith" }
  ],
  "availableSlots": [
    {
      "start": "2025-01-22T10:00:00Z",
      "end": "2025-01-22T11:00:00Z"
    },
    {
      "start": "2025-01-22T11:00:00Z",
      "end": "2025-01-22T12:00:00Z"
    }

  ],
  "workHours": {"startHour": 9, "endHour": 17},
  "humanReadable": {
    "availableSlots": [
      {
        "start": "Wednesday, January 22, 2025 at 10:00 AM",
        "end": "Wednesday, January 22, 2025 at 11:00 AM"
      },
      {
        "start": "Wednesday, January 22, 2025 at 11:00 AM",
        "end": "Wednesday, January 22, 2025 at 12:00 PM"
      }
    ],
    "interviewerBusyTimes": ["list of interviewers busy times for each interviewer in a easily readable format"],
    "workHours": "9:00 - 17:00",
  }
}
```

### Performance Considerations
I implemented a one pass algorithm for determining the available interview slots, which also uses a sort to create the window of events. Hence the algorithm runs in O(nlogn), n = number of busyblocks of all interviewers in the interviewtemplate. 

This algorithm works by creating a events array of tuples (start/end, +1,-1) sorting it by time, then creating a availabilitywindow array by sweeping the events array and adding an available window when the delta sum is equal to zero, and then creating a availableinterviewtimes array based off that availablewindow array, where we also enforce all contraints to make sure the availableinterviewtimes are valid, jumping up by 30 minutes as we process availableinterviewtimes within each window to make sure interviews start on :00 or :30.

### Test Cases
1) Template not found → 404

Test: test_404_when_template_not_found
Why: If the template ID doesn’t exist, the API should return a clear 404 with an error body—no ambiguous 200s.

Calls /api/interviews/{nonexistent}/availability/

Asserts: status=404 and an "error" key in the JSON.

2) Invalid time range → 400

Test: test_400_when_end_before_start
Why: Basic input validation: end must be after start.

Calls with start=2030-01-02T10:00Z and end=2030-01-01T10:00Z.

Asserts: status=400 and an "error" message.

3) Invalid work hours → 400

Test: test_400_when_invalid_hour_values
Why: Validate start_hour/end_hour are in 0..23 and start_hour < end_hour.

Cases:

start_hour=25 (too large) → 400

end_hour=-1 (negative) → 400

start_hour >= end_hour → 400 (checked twice)

Asserts: status=400 for each

4) Duration, alignment, and “all free” on a realistic day

Test: test_slots_respect_duration_half_hour_and_all_interviewers_free
Why: The core behavior: produce only valid, aligned slots where everyone is free.

Scenario (UTC, 2030-01-01, 09:00–17:00, 60-min):

Alice busy: [09:30,10:30), [13:00,13:30)

Bob busy: [10:00,11:00), [15:30,17:00)

Half-open semantics: a block [A,B) occupies A through just before B. Back-to-back is allowed (e.g., a slot ending at 11:00 can abut a busy block starting at 11:00).

Common free windows computed:

[09:00,09:30) (too short for 60m; ignored)

[11:00,13:00) → 11:00–12:00, 11:30–12:30, 12:00–13:00

[13:30,15:30) → 13:30–14:30, 14:00–15:00, 14:30–15:30

The test asserts:

HTTP 200

Exactly those six slots, in ISO Z

Every start minute is 0 or 30, seconds 0

Duration is exactly 60m

Response "interviewers" includes the mocked names (“Alice”, “Bob”) to show we surface names if the busy provider supplies them

5) Work hours filter limits valid slots

Test: test_work_hours_filter_applied
Why: Even if the day has free windows, work hours (e.g., [10, 12]) should prune slots that start or end outside the allowed window.

Reuses the busy day above.

With start_hour=10 and end_hour=12, only 11:00–12:00 fits fully within 10:00–12:00.

Asserts: the only slot returned is 11:00–12:00.

6) 24-hour minimum start is enforced

Test: test_24h_rule_minimum_start_enforced
Why: No slot may start within 24 hours from now.

Mocks a completely free calendar.

Calls with start = now + 1h and end = now + 3d, and wide work hours to avoid filtering.

The view pushes the earliest candidate start to ceil_to_half_hour(now+24h).

Asserts:

We get some slots (window is 3 days and fully free).

Every returned slot start >= ceil_to_half_hour(now+24h).

Starts align to :00/:30 with zero seconds.

Note: “ceil to half hour” means:

12:00:00 → 12:00

12:00:01 → 12:30

12:30:00 → 12:30

12:30:01 → 13:00

7) Any overlap with a busy block excludes the slot

Test: test_excludes_slots_where_any_interviewer_is_busy
Why: The API must reject every slot that overlaps any interviewer’s busy period.

Scenario (UTC, 2030-01-02, 09:00–13:00, 60-min):

Alice: free all morning

Bob: busy [11:00,12:00)

Candidate starts on :00/:30 (60m):

09:00–10:00 yes

09:30–10:30 yes

10:00–11:00 yes

10:30–11:30 no (overlaps 11:00–11:30)

11:00–12:00 no (exactly the busy block)

11:30–12:30 no (overlaps 11:30–12:00)

12:00–13:00 yes

The test asserts:

Those three overlapping slots are not present

The non-overlapping neighbors are present


## Edge Cases Handled

### Same timestamp proccessing
What: because busy timestamps can end exactly when another starts, we need to make sure we do not accidentally add false "free" times to our available array when we are sweeping our delta events array in the case where one event frees up, subtracting the amount_busy to 0, and another event becomes busy, making the amount_busy to 1

Why: this matters because if you are handling alot of busy times that end and start at the same time, your available array will be clouded with events that start and end at the same time ex. 11:00 - 11:00 because the program would register that as a free time because the amount busy was 0. while this wouldnt effect the output of the program, it could severly effect the performance of the endpoint if there are many instances where this occurs

How I handled it: since we are keeping track of the prev_time and current time as we are sweeping our events array, we can make a comparison to make sure that prev_time is not equal to current time along with the amount_busy being equal to 0. this prevents these ghost availibilitys from clouding the available array


### Availability near end of search window
What: when we are creating available windows, we need to make sure the start time + duration is still less than the end of the search window even if that time is considered free

Why: if we do not handle this case, we may accidentally create available times that fall outside of the search window, that were very close to the end. 

How I handled it: for every window we process in free windows array as we are creating availble times, we create a last_valid_start variable, which is the window_end - interview duration. this avoids ever trying to create available times that have a greater start time than the last_valid_start

### Inconsistent date time values
What: we may end up with datetime values with varying formats when receiving busy time arrays (naive, explicit offset)

Why: this can cause issues when trying to compare two different datetimes with different formats, we make alot of date comparisons in our code so this would cause major errors.

How I handled it: every datetime we process from the busy times from the interviewers, we first convert to a common UTC with a trailing Z format. this ensures as all of the datetimes flow through the algorithm, they are of a consistent format