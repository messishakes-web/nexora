
from rest_framework import serializers

from .models import ParentContact


class ParentContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParentContact
        fields = [
            "id",
            "full_name",
            "relationship",
            "phone_number",
        ]
