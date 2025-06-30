from django.db import models


class Contact(models.Model):
    id = models.AutoField(primary_key=True, verbose_name=("ID"))
    """basic contact number"""
    name = models.CharField(max_length=256)
    number = models.CharField(max_length=256)
    description = models.TextField()

    def __str__(self):
        return "%s : %s " % (self.name, self.number)
