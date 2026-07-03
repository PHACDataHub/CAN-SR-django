from django.apps import AppConfig


class CoreAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "proj"

    def ready(self):
        # signals need to be imported somewhere
        # this is the most appropriate
        import proj.signals
