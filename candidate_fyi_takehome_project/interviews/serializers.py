from datetime import timedelta, timezone
from django.utils import timezone as dj_tz
from rest_framework import serializers

class AvailabilityQuerySerializer(serializers.Serializer):
    # All optional; defaults handled in the view after validation
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)
    start_hour = serializers.IntegerField(required=False, min_value=0, max_value=23)
    end_hour = serializers.IntegerField(required=False, min_value=0, max_value=23)

    def validate(self, attrs):
        # If both provided, enforce end > start
        start = attrs.get("start")
        end = attrs.get("end")
        if start and end and end <= start:
            raise serializers.ValidationError({"end": "end must be after start"})

        # If both provided, enforce hour order
        sh = attrs.get("start_hour")
        eh = attrs.get("end_hour")
        if sh is not None and eh is not None and sh >= eh:
            raise serializers.ValidationError({"end_hour": "end_hour must be after start_hour"})

        return attrs


# --- Output serializers  ---

class InterviewerOut(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

class SlotOut(serializers.Serializer):
    start = serializers.CharField()  
    end = serializers.CharField()

class WorkHoursOut(serializers.Serializer):
    startHour = serializers.IntegerField()
    endHour = serializers.IntegerField()

class HumanReadableSlotOut(serializers.Serializer):
    start = serializers.CharField()
    end = serializers.CharField()

class HumanReadableOut(serializers.Serializer):
    availableSlots = HumanReadableSlotOut(many=True)
    interviewerBusyTimes = serializers.ListField()  
    workHours = serializers.CharField()

class AvailabilityResponseSerializer(serializers.Serializer):
    interviewId = serializers.IntegerField()
    name = serializers.CharField()
    durationMinutes = serializers.IntegerField()
    interviewers = InterviewerOut(many=True)
    availableSlots = SlotOut(many=True)
    workHours = WorkHoursOut()
    humanReadable = HumanReadableOut()
