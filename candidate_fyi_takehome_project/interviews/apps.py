from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class InterviewsConfig(AppConfig):
    name = "candidate_fyi_takehome_project.interviews"
    verbose_name = _("Interviews")