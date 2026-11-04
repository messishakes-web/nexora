
"""
Django settings for config project.
"""
 
from decouple import config
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# SECURITY
SECRET_KEY = 'django-insecure-4!p(l#qpetz2)t$k=%&8*@d^#igg^0x!g%7j&9n_hk2bzou=fd'

DEBUG = True

ALLOWED_HOSTS = ['127.0.0.1', 'localhost']


# APPLICATIONS
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'students',
]


# MIDDLEWARE
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# URLS AND TEMPLATES
ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# DATABASE
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# PASSWORD VALIDATION
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': (
            'django.contrib.auth.password_validation.'
            'UserAttributeSimilarityValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.'
            'MinimumLengthValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.'
            'CommonPasswordValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.'
            'NumericPasswordValidator'
        ),
    },
]


# INTERNATIONALIZATION
LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Africa/Nairobi'

USE_I18N = True

USE_TZ = True


# STATIC FILES
STATIC_URL = 'static/'


# EMAIL
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


# DJANGO REST FRAMEWORK
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}


# DEFAULT PRIMARY KEY
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Nexora Daraja sandbox configuration
DARAJA_CONSUMER_KEY = config("DARAJA_CONSUMER_KEY", default="")
DARAJA_CONSUMER_SECRET = config("DARAJA_CONSUMER_SECRET", default="")
DARAJA_BASE_URL = config(
    "DARAJA_BASE_URL",
    default="https://sandbox.safaricom.co.ke",
)
DARAJA_SHORTCODE = config("DARAJA_SHORTCODE", default="")
DARAJA_PASSKEY = config("DARAJA_PASSKEY", default="")
DARAJA_CALLBACK_URL = config("DARAJA_CALLBACK_URL", default="")
DARAJA_ENVIRONMENT = "sandbox"
