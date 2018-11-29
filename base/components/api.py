from django.db.models import QuerySet
from rest_framework.generics import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView
from inspect import getmembers

from base.components.encoders import EmberJSONRenderer


def _is_extra_action(attr):
    return hasattr(attr, 'bind_to_methods')


class Api(APIView):
    queryset = None
    serializer_class = None
    read_serializer_class = None
    write_serializer_class = None
    renderer_classes = (EmberJSONRenderer,)
    # If you want to use object lookups other than pk, set 'lookup_field'.
    # For more complex lookup requirements override `get_object()`.
    lookup_field = 'pk'
    lookup_url_kwarg = None

    # The filter backend classes to use for queryset filtering
    filter_backends = api_settings.DEFAULT_FILTER_BACKENDS

    # The style to use for queryset pagination.
    pagination_class = api_settings.DEFAULT_PAGINATION_CLASS

    @classmethod
    def get_extra_actions(cls):
        """
        Get the methods that are marked as an extra ViewSet `@action`.
        """
        return [method for _, method in getmembers(cls, _is_extra_action)]

    def get_queryset(self):
        """
        Get the list of items for this view.
        This must be an iterable, and may be a queryset.
        Defaults to using `self.queryset`.

        This method should always be used rather than accessing `self.queryset`
        directly, as `self.queryset` gets evaluated only once, and those results
        are cached for all subsequent requests.

        You may want to override this if you need to provide different
        querysets depending on the incoming request.

        (Eg. return a list of items that is specific to the user)
        """
        assert self.queryset is not None, (
                "'%s' should either include a `queryset` attribute, "
                "or override the `get_queryset()` method."
                % self.__class__.__name__
        )

        queryset = self.queryset
        if isinstance(queryset, QuerySet):
            # Ensure queryset is re-evaluated on each request.
            queryset = queryset.all()
        return queryset

    def get_object(self, pk):
        """
        Returns the object the view is displaying.

        You may want to override this if you need to provide non-standard
        queryset lookups.  Eg if objects are referenced using multiple
        keyword arguments in the url conf.
        """
        queryset = self.filter_queryset(self.get_queryset())

        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field

        assert lookup_url_kwarg in self.kwargs, (
                'Expected view %s to be called with a URL keyword argument '
                'named "%s". Fix your URL conf, or set the `.lookup_field` '
                'attribute on the view correctly.' %
                (self.__class__.__name__, lookup_url_kwarg)
        )

        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        obj = get_object_or_404(queryset, **filter_kwargs)

        # May raise a permission denied
        self.check_object_permissions(self.request, obj)

        return obj

    def get_serializer(self, *args, **kwargs):
        """
        Return the serializer instance that should be used for validating and
        deserializing input, and for serializing output.
        """
        serializer_class = self.get_serializer_class()
        kwargs['context'] = self.get_serializer_context()
        return serializer_class(*args, **kwargs)

    def get_serializer_class(self):
        """Define your HTTP method-to-serializer mapping freely.
        This also works with CoreAPI and Swagger documentation,
        which produces clean and readable API documentation,
        so I have chosen to believe this is the way the
        Django REST Framework author intended things to work:"""

        if self.request.method in ['GET'] and self.read_serializer_class is not None:
            # Since the ReadSerializer does nested lookups in multiple tables, use read_serializer_class
            # to nest related objects
            return self.read_serializer_class

        elif self.write_serializer_class is not None:
            # use write_serializer_class to specify the id of related object
            return self.write_serializer_class
        elif self.serializer_class is not None:
            return self.serializer_class
        else:
            raise Exception("'%s' should either include a `serializer_class` attribute, "
                            "or override the `get_serializer_class()` method."
                            % self.__class__.__name__)

    def get_serializer_context(self):
        """
        Extra context provided to the serializer class.
        """
        return {
            'request': self.request,
            'format': self.format_kwarg,
            'view': self
        }

    def filter_queryset(self, queryset):
        """
        Given a queryset, filter it with whichever filter backend is in use.

        You are unlikely to want to override this method, although you may need
        to call it either from a list view, or from a custom `get_object`
        method if you want to apply the configured filtering backend to the
        default queryset.
        """
        for backend in list(self.filter_backends):
            queryset = backend().filter_queryset(self.request, queryset, self)
        return queryset

    @property
    def paginator(self):
        """
        The paginator instance associated with the view, or `None`.
        """
        if not hasattr(self, '_paginator'):
            if self.pagination_class is None:
                self._paginator = None
            else:
                self._paginator = self.pagination_class()
        return self._paginator

    def paginate_queryset(self, queryset):
        """
        Return a single page of results, or `None` if pagination is disabled.
        """
        if self.paginator is None:
            return None
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        """
        Return a paginated style `Response` object for the given output data.
        """
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data)

    def create(self, request, pk, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.after_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def retrieve(self, request, pk, *args, **kwargs):
        instance = self.get_object(pk)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def update(self, request, pk, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object(pk)
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.after_update(serializer)

        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    def destroy(self, request, pk, *args, **kwargs):
        instance = self.get_object(pk)
        self.after_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def after_destroy(self, instance):
        """

        :param instance:
        :return:
        """
        instance.delete()

    def partial_update(self, request, pk, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, pk, *args, **kwargs)

    def after_update(self, serializer):
        serializer.save()

    def after_create(self, serializer):
        serializer.save()

    def get_success_headers(self, data):
        try:
            return {'Location': str(data[api_settings.URL_FIELD_NAME])}
        except (TypeError, KeyError):
            return {}

    def post(self, request, pk=None, *args, **kwargs):
        return self.create(request, pk, *args, **kwargs)

    def get(self, request, pk=None, *args, **kwargs):
        if pk:
            return self.retrieve(request, pk, *args, **kwargs)
        return self.list(request, pk, *args, **kwargs)

    def delete(self, request, pk=None, *args, **kwargs):
        return self.destroy(request, pk, *args, **kwargs)

    def put(self, request, pk=None, *args, **kwargs):
        return self.update(request, pk, *args, **kwargs)

    def patch(self, request, pk=None, *args, **kwargs):
        return self.partial_update(request, pk, *args, **kwargs)
