from django.db import models
from django.utils import timezone

# Create your models here.
class Student(models.Model):
    card_id = models.IntegerField()
    name = models.CharField(max_length=50, blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    sex = models.CharField(max_length=7, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        if self.name == None:
            return str(self.card_id)
        else:
            return str(self.name) + ' : ' + str(self.id)


class Log(models.Model):
    ida = models.IntegerField(default=0)
    card_id = models.IntegerField()
    name = models.CharField(max_length=50)
    date = models.DateField(default=timezone.now)
    time_in = models.TimeField(default=timezone.now)
    time_out = models.TimeField(blank=True, null=True)
    status = models.TextField(max_length=100)

    def __str__(self):
        return str(self.name) + ' : ' + str(self.date)