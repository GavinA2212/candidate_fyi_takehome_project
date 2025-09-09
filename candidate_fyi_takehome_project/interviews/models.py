from django.db import models

# Create your models here.

class Interviewer(models.Model):

    def __str__(self):
        return self.name
    
class InterviewTemplate(models.Model):
    name = models.CharField(max_length=255)
    duration = models.IntegerField()  # Duration in minutes
    interviewers = models.ManyToManyField(Interviewer, related_name='interview_templates')

    def __str__(self):
        return self.name