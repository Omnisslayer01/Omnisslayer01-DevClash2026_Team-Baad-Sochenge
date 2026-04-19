import io
from unittest.mock import patch, MagicMock
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from accounts.models import User

class ExtractIdDataTests(APITestCase):
    """OCR name extraction from synthetic Tesseract output."""

    @patch("verification.services._run_tesseract_variants")
    def test_name_extracted_from_label_line(self, mock_ocr):
        from verification.services import extract_id_data

        mock_ocr.return_value = (
            "Government of India\n"
            "Name: RAHUL KUMAR SHARMA\n"
            "DOB: 01/01/1990\n"
        )
        uploaded = self._tiny_jpeg_upload()
        name, _masked = extract_id_data(uploaded)
        self.assertIn("RAHUL", name.upper())
        self.assertIn("SHARMA", name.upper())

    def _tiny_jpeg_upload(self):
        file = io.BytesIO()
        image = Image.new("RGB", (80, 80), color=(200, 200, 200))
        image.save(file, "JPEG")
        file.seek(0)
        return SimpleUploadedFile("id.jpg", file.read(), content_type="image/jpeg")


class NamesLikelyMatchTests(APITestCase):
    """Unit tests for OCR vs profile name alignment."""

    def test_reordered_tokens_match(self):
        from verification.services import names_likely_match

        self.assertTrue(names_likely_match("John Doe", "Doe John"))

    def test_fuzzy_ocr_typo(self):
        from verification.services import names_likely_match

        self.assertTrue(names_likely_match("Jon Doe", "John Doe"))


class IdentityVerificationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            password="testpassword",
            full_name="John Doe"
        )
        self.client.force_authenticate(user=self.user)
        self.url = reverse('verify_identity')

    def create_dummy_image(self, name='test.jpg'):
        file = io.BytesIO()
        image = Image.new('RGB', (100, 100), color=(73, 109, 137))
        image.save(file, 'JPEG')
        file.name = name
        file.seek(0)
        return SimpleUploadedFile(name, file.read(), content_type='image/jpeg')

    @patch('verification.services.pytesseract.image_to_string')
    @patch('verification.services.boto3.client')
    def test_verify_identity_happy_path(self, mock_boto, mock_tesseract):
        # Setup mocks
        mock_tesseract.return_value = "John Doe\nID Card ABC123456789"
        
        mock_rekognition = MagicMock()
        mock_rekognition.compare_faces.return_value = {
            'FaceMatches': [{'Similarity': 95.5}]
        }
        mock_boto.return_value = mock_rekognition

        data = {
            'id_image': self.create_dummy_image('id.jpg'),
            'selfie_image': self.create_dummy_image('selfie.jpg'),
            'liveness_passed': True,
            'user_name': 'John Doe'
        }

        response = self.client.post(self.url, data, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['verified'])
        self.assertEqual(response.data['confidence'], 90) # 50 (sim) + 20 (live) + 20 (name)
        self.assertEqual(response.data['face_similarity'], 95.5)

    def test_verify_identity_liveness_fail(self):
        data = {
            'id_image': self.create_dummy_image('id.jpg'),
            'selfie_image': self.create_dummy_image('selfie.jpg'),
            'liveness_passed': False,
            'user_name': 'John Doe'
        }

        response = self.client.post(self.url, data, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['verified'])
        self.assertFalse(response.data['liveness'])
        self.assertEqual(response.data['confidence'], 0)

    @patch('verification.services.pytesseract.image_to_string')
    @patch('verification.services.boto3.client')
    def test_verify_identity_name_mismatch(self, mock_boto, mock_tesseract):
        mock_tesseract.return_value = "Alice Murphy\nID Card"
        
        mock_rekognition = MagicMock()
        mock_rekognition.compare_faces.return_value = {
            'FaceMatches': [{'Similarity': 95.5}]
        }
        mock_boto.return_value = mock_rekognition

        data = {
            'id_image': self.create_dummy_image('id.jpg'),
            'selfie_image': self.create_dummy_image('selfie.jpg'),
            'liveness_passed': True,
            'user_name': 'John Doe'
        }

        response = self.client.post(self.url, data, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['verified'])
        self.assertFalse(response.data['name_match'])
        self.assertEqual(response.data['confidence'], 70) # 50 (sim) + 20 (live) + 0 (name)
