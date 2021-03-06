import importlib.util
import uuid
from wsgiref.util import FileWrapper

from django.conf import settings
from django.db.models import CharField, Count, F, Value
from django.db.models.functions import Concat
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from PIL import Image
from rest_framework import generics, status
from rest_framework.response import Response

from .models import Wallpaper, Like, Report
from .serializers import (LikesSerializer, WallpaperDetailsSerializer,
                          WallpaperSerializer, ReportsSerializer)


class CreateView(generics.ListCreateAPIView):

    def __init__(self):
        self.id = None
        self.size = None
        self.ext = None
        self.logo_size = 1

    """This class defines the create behavior of our WP api."""

    serializer_class = WallpaperSerializer

    def get_queryset(self):
        """
        Override get_queryset() to filter on multiple values for 'created'
        """
        reports = Count('report', distinct=True)
        likes = Count('like', distinct=True)
        queryset = Wallpaper.objects.filter(status="Active").annotate(
            url=Concat(Value(settings.WALLPAPERS_URL),
                       F('id'), Value('.'), F('ext'),
                       output_field=CharField())).annotate(reports=reports).annotate(likes=likes)

        category = self.request.query_params.get('category', None)
        if category:
            queryset = queryset.filter(category=category)

        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(title__icontains=search)

        return queryset

    def get(self, request, *args, **kwargs):

        self.serializer_class = WallpaperDetailsSerializer
        return self.list(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):

        for i in range(int(request.POST['count'])):

            uploaded_file = request.FILES['file' + str(i)]
            if uploaded_file.content_type == 'image/png':
                self.ext = 'png'
            elif uploaded_file.content_type == 'image/jpeg':
                self.ext = 'jpg'
            elif uploaded_file.content_type == 'image/gif':
                self.ext = 'gif'
            else:
                # Invalid file type
                return Response(status=status.HTTP_400_BAD_REQUEST)

            self.id = uuid.uuid4()

            filename = "{}{}.{}".format(
                settings.WALLPAPERS_ABSOLUTE_PATH, self.id, self.ext)

            with open(filename, 'wb+') as temp_file:
                for chunk in uploaded_file.chunks():
                    temp_file.write(chunk)

            Image.MAX_IMAGE_PIXELS = None
            im = Image.open(filename)
            self.size = im.size

            if 'logoSize' in request.POST:
                if request.POST['logoSize'] == 'large':
                    self.logo_size = 1.4
                elif request.POST['logoSize'] == 'small':
                    self.logo_size = 0.6

            try:
                self.create(request, *args, **kwargs)
            except ():
                return Response({ 'success': False }, status=status.HTTP_400_BAD_REQUEST)

        return Response({ 'success': True }, status=status.HTTP_201_CREATED)


    def perform_create(self, serializer):
        """Save the post data when creating a new wallpaper."""

        serializer.save(id=self.id, resolution='{} x {}'.format(
            self.size[0], self.size[1]), logo_size=self.logo_size,
            category=self._get_category(), ext=self.ext)


    def _get_category(self):
        """ Get Category from resolution """

        max_size = max(self.size[0], self.size[1])
        category = 'phone'
        if max_size > 7500:
            category = '8k'
        elif max_size > 4500:
            category = '5k'
        elif max_size > 3500:
            category = '4k'
        elif max_size > 1500:
            category = 'tablet'

        return category


class DetailsView(generics.RetrieveUpdateDestroyAPIView):

    """This class handles the http GET, PUT and DELETE requests."""

    reports = Count('report', distinct=True)
    likes = Count('like', distinct=True)
    queryset = Wallpaper.objects.annotate(
        likes=likes, reports=reports,
        url=Concat(Value(settings.WALLPAPERS_URL), F('id'), Value('.'),
                   F('ext'), output_field=CharField()))

    serializer_class = WallpaperDetailsSerializer


class CreateReport(generics.CreateAPIView):

    """ Create Report for wallpaper """

    def post(self, request, pk, *args, **kwargs):
        ip = get_client_ip(request)

        wp = Wallpaper.objects.filter(id=uuid.UUID(pk)).first()
        if wp is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        likes = 0
        reports = Report.objects.filter(wallpaper=pk).count()
        if reports > 0:
            likes = Like.objects.filter(wallpaper=pk).count()

        if reports >= likes:
            wp.status = "Reported"
            wp.save()

        data = {'ip': ip, 'wallpaper': wp.id}
        serializer = ReportsSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CreateLike(generics.CreateAPIView):

    """ Create Like for wallpaper """

    def post(self, request, pk, *args, **kwargs):
        ip = get_client_ip(request)
        wp = Wallpaper.objects.get(id=pk)

        data = {'ip': ip, 'wallpaper': wp.id}
        serializer = LikesSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DownloadView(generics.GenericAPIView):

    def get(self, request, pk, *args, **kwargs):

        wp = Wallpaper.objects.filter(id=pk).first()

        if (wp is None):
            return Response(status=status.HTTP_404_NOT_FOUND)

        wp.downloads += 1
        wp.save()

        file_name = uuid.UUID(pk)
        fsock = open("{}{}.{}".format(settings.WALLPAPERS_ABSOLUTE_PATH,
                                      file_name, wp.ext), "rb")
        response = HttpResponse(
            FileWrapper(fsock), content_type='image/jpeg')
        response['Content-Disposition'] = 'attachment; filename={}.jpg'.format(
            file_name)
        return response


def get_client_ip(request):
    """ Get IP addres of the client """

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
