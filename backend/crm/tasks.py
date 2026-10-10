from celery import shared_task

from .services import apagar_triagens_abandonadas


@shared_task
def apagar_triagens_abandonadas_task():
    return apagar_triagens_abandonadas()


@shared_task
def processar_notificacoes_task():
    from .notifications import processar_automaticas
    return processar_automaticas()
