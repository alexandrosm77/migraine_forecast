from django.urls import path, include
from django.contrib import admin
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('forecast.urls')),
    path('login/', auth_views.LoginView.as_view(template_name='forecast/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='forecast:index'), name='logout'),
]
