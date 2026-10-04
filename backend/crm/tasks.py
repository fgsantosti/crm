from celery import shared_task

from .services import classificar_triagens_abandonadas


@shared_task
def classificar_triagens_abandonadas_task():
    return classificar_triagens_abandonadas()
