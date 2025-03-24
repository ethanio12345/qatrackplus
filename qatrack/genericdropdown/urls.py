from django.conf.urls import url
from .views import updateCombo

urlpatterns = [
    url(r'^updatecombo/(?P<id>\d+)?$', updateCombo, name='updatecombo'),
]