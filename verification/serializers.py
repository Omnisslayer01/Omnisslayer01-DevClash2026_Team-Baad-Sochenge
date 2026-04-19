from rest_framework import serializers

from .models import UserVerification

_ALLOWED_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


def _validate_image_extension(value):
    name = (getattr(value, "name", "") or "").lower()
    if not name.endswith(_ALLOWED_IMAGE_SUFFIXES):
        raise serializers.ValidationError("Only PNG and JPG images are allowed.")
    return value


class IdentityVerificationRequestSerializer(serializers.Serializer):
    """
    Serializer for the identity verification request from frontend.
    """

    id_image = serializers.ImageField(required=False)
    selfie_image = serializers.ImageField()
    liveness_passed = serializers.BooleanField()
    user_name = serializers.CharField(max_length=255)
    id_process_token = serializers.CharField(required=False, allow_blank=True)

    def validate_id_image(self, value):
        return _validate_image_extension(value)

    def validate_selfie_image(self, value):
        return _validate_image_extension(value)


class PreProcessIDSerializer(serializers.Serializer):
    """
    Serializer for the ID image upload to be processed immediately.
    """

    id_image = serializers.ImageField()

    def validate_id_image(self, value):
        return _validate_image_extension(value)

class IdentityVerificationResponseSerializer(serializers.ModelSerializer):
    """
    Serializer for the identity verification API response.
    """
    verified = serializers.BooleanField(source='is_identity_verified')
    confidence = serializers.IntegerField(source='verification_confidence')
    liveness = serializers.BooleanField(source='liveness_passed')

    class Meta:
        model = UserVerification
        fields = [
            'verified', 
            'confidence', 
            'face_similarity', 
            'liveness', 
            'name_match',
            'extracted_name',
            'masked_id_number'
        ]
