from django.conf.urls import *

from genericdropdown.views import updateCombo

urlpatterns = [
    url(r'^updatecombo/(?P<id>\d+)?$', updateCombo, name='updatecombo'),
]
