
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    is_verified = models.BooleanField(default=False)
    trust_score = models.IntegerField(default=20)
    is_reported = models.BooleanField(default=False)
    def __str__(self):
        return self.username

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    skills = models.TextField(blank=True)
    company = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)


    def is_complete(self):
        return all([self.name, self.skills, self.company])

    def __str__(self):
        return self.name

class Connection(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ]

    user_from = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_connections')
    user_to = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_connections')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')

    def __str__(self):
        return f"{self.user_from} -> {self.user_to} ({self.status})"

class Report(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Report on {self.user.username}"

