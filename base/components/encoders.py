from rest_framework.renderers import JSONRenderer
from django.db import models
from enumfields import Enum
from rest_framework.utils.encoders import JSONEncoder


class CustomJsonEncoder(JSONEncoder):
    """
        CustomJsonEncoder subclass that encode types that JSONEncoder don't know how to encode them
    """
    def default(self, obj):

        if isinstance(obj, Enum):
            return obj.value

        if isinstance(obj, models.Model):
            from django.forms.models import model_to_dict
            return model_to_dict(obj)

        return super(CustomJsonEncoder, self).default(obj)


class EmberJSONRenderer(JSONRenderer):
    """
    Replace encoder_class of JSONRenderer by CustomJsonEncoder
    """
    encoder_class = CustomJsonEncoder
