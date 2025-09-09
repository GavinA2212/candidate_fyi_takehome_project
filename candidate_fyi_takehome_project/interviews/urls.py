from django.urls import path
from candidate_fyi_takehome_project.interviews.views import InterviewAvailabilityView
app_name = "interviews"

urlpatterns = [
    path("<int:id>/availability/", InterviewAvailabilityView.as_view(), name="interview-availability"),
]