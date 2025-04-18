from django.urls import path
from . import views

app_name = 'forecast'

urlpatterns = [
    path('', views.index, name='index'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('locations/', views.location_list, name='location_list'),
    path('locations/add/', views.location_add, name='location_add'),
    path('locations/<int:location_id>/', views.location_detail, name='location_detail'),
    path('locations/<int:location_id>/delete/', views.location_delete, name='location_delete'),
    path('predictions/', views.prediction_list, name='prediction_list'),
    path('predictions/<int:prediction_id>/', views.prediction_detail, name='prediction_detail'),
    path('comparison/', views.comparison_report, name='comparison_report'),
    path('comparison/<int:location_id>/', views.comparison_detail, name='comparison_detail'),
    path('accounts/register/', views.register, name='register'),
    path('accounts/profile/', views.profile, name='profile'),
]
