# Infraestrutura de desenvolvimento

## Serviços

| Serviço | Função |
| --- | --- |
| db | PostgreSQL 17 com volume persistente |
| redis | Broker Celery, resultados e camada Channels em bancos lógicos separados |
| setup | Migrações e coleta dos arquivos estáticos antes de iniciar a aplicação |
| web | Django em Python 3.12, servido por Uvicorn e ASGI |
| worker | Execução de tarefas Celery |
| beat | Agendador Celery com configuração persistida no PostgreSQL |
| frontend | Build React servido por Nginx |
| proxy | Caddy direcionando interface, API, admin e WebSocket no mesmo domínio |

Somente o proxy publica uma porta no host, restrita a localhost. Banco, Redis e backend ficam na rede interna do Compose. O endpoint de prontidão verifica o acesso ao PostgreSQL sem expor detalhes de erro.

Não há tarefas comerciais agendadas nesta etapa. A camada Channels está configurada, mas nenhuma rota WebSocket está disponível até implementar tickets e permissões. Armazenamento de mídia em S3 ou MinIO será preparado na etapa de mídia.

## Subir a aplicação

Pré requisitos: Docker Engine e Docker Compose v2 com suporte a dependências por serviço concluído.

Injete `DJANGO_SECRET_KEY` e `POSTGRES_PASSWORD` no ambiente do terminal por um cofre ou ambiente protegido. Não crie arquivo com segredos no workspace. O Compose exige ambas e não define valores padrão para elas.

Na raiz do projeto:

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose exec web python manage.py createsuperuser
```

Não use `docker compose config` sem `--quiet` em saídas compartilhadas, pois a expansão pode revelar variáveis de ambiente.

Endereços:

* Interface: http://localhost:8080
* Administração: http://localhost:8080/admin/
* API: http://localhost:8080/api/
* Prontidão: http://localhost:8080/health/ready/

O frontend compilado usa `/api`, sem um endereço externo fixo. O login continua usando o mecanismo da base anterior; a migração para sessão com cookie e CSRF será uma entrega própria.

## Verificações

```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py test crm
docker compose exec worker celery -A config inspect ping
docker compose logs --tail=50 web worker beat setup
```

Os testes Django usam um banco de teste separado criado pelo framework. Não execute essa suíte com credenciais ou banco de produção.

Para compilar a interface localmente:

```bash
cd frontend
npm ci
npm run build
```

Para parar sem excluir os dados:

```bash
docker compose down
```

Volumes preservam banco, Redis e arquivos estáticos. Rode apenas uma instância de beat para evitar agendamentos duplicados. Após novas migrações, execute novamente o serviço setup antes de reiniciar os serviços da aplicação.

## Limites desta entrega

A configuração usa HTTP em localhost para desenvolvimento. Publicação externa requer configurar o domínio e HTTPS no Caddy, cookies seguros e origens CSRF correspondentes. As permissões por papel, novo modelo de requisições, outbox, adaptador OpenClaw e eventos em tempo real serão implementados nas etapas seguintes.

Referências de configuração: [integração Django com Celery](https://github.com/celery/celery/blob/main/docs/django/first-steps-with-django.rst), [Channels](https://channels.readthedocs.io/en/latest/index.html) e [camada Redis](https://github.com/django/channels_redis/blob/main/README.rst).
