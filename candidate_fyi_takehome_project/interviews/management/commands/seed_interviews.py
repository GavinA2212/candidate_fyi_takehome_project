from django.core.management.base import BaseCommand
from candidate_fyi_takehome_project.interviews.models import Interviewer, InterviewTemplate
from faker import Faker

class Command(BaseCommand):
    help = 'Seeds the database with interviewers and interview templates'

    def handle(self, *args, **options):
        fake = Faker()
        
        self.stdout.write('Creating interviewers...')
        interviewers = []
        for _ in range(5):
            interviewer = Interviewer.objects.create()
            interviewers.append(interviewer)
            self.stdout.write(f'Created interviewer: {interviewer.id}')
        
        self.stdout.write('Creating interview templates...')
        interview_types = [
            {'name': 'Technical Interview', 'duration': 60},
            {'name': 'Behavioral Interview', 'duration': 45},
            {'name': 'System Design', 'duration': 90},
            {'name': 'Coding Challenge', 'duration': 120}
        ]
        
        for interview_type in interview_types:
            template = InterviewTemplate.objects.create(
                name=interview_type['name'],
                duration=interview_type['duration']
            )
            
            # Assign random interviewers (at least 2 per template)
            import random
            assigned_interviewers = random.sample(interviewers, random.randint(2, 4))
            template.interviewers.set(assigned_interviewers)
            
            self.stdout.write(f'Created template: {template.name} with {template.interviewers.count()} interviewers, id: {template.id}')
        
        self.stdout.write(self.style.SUCCESS('Successfully seeded the database!'))