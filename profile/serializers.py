from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from profile import models

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.UserProfile
        fields = ('id','email','name','password')
        extra_kwargs = {
            'password' : {
                'write_only': True,
                'style': {
                    'input_type':'password'
                }
            }
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is not None:
            return attrs
        password = attrs.get("password")
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        except Exception as exc:
            raise serializers.ValidationError(
                {"password": ["Password could not be validated."]}
            ) from exc
        return attrs

    def create(self, validated_data):
        user = models.UserProfile.objects.create_user(
            email = validated_data['email'],
            name = validated_data['name'],
            password = validated_data['password']
        )

        return user
    
    def update(self, instance, validated_data):
        if 'password' in validated_data:
            password = validated_data.pop('password')
            instance.set_password(password)

        return super().update(instance, validated_data)