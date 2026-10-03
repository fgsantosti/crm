from django.db.models import Case, When, Value, IntegerField
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Company, Lead, Question, Event
from .serializers import CompanySerializer, LeadSerializer, QuestionSerializer, IncomingSerializer, EventSerializer, DeliverySerializer
from .services import receive, escalate

class CompanyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CompanySerializer
    def get_queryset(self): return self.request.user.companies.all()
    @action(detail=True, methods=["post"])
    def incoming(self, request, pk=None):
        company = self.get_object()
        data = IncomingSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(receive(company, data.validated_data))
    @action(detail=True, methods=["post"])
    def delivery(self, request, pk=None):
        from django.db import transaction
        authorized_company = self.get_object()
        payload = DeliverySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with transaction.atomic():
            company = Company.objects.select_for_update().get(pk=authorized_company.pk)
            event = get_object_or_404(Event.objects.select_for_update(), pk=payload.validated_data["event_id"], lead__company=company)
            value = payload.validated_data["status"]
            if value not in ["SENT", "FAILED"]: return Response({"detail": "status deve ser SENT ou FAILED"}, status=400)
            if event.delivery == "PENDING":
                event.delivery = value
                event.save()
                if value == "FAILED": escalate(event.lead, "Falha de envio: revisar entrega antes de qualquer retomada")
            return Response({"delivery": event.delivery})

class TenantMixin:
    def company(self):
        return get_object_or_404(self.request.user.companies.all(), pk=self.request.query_params.get("company"))
    def get_queryset(self): return self.queryset.filter(company=self.company())

class LeadViewSet(TenantMixin, viewsets.ModelViewSet):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    http_method_names = ["get", "patch", "head", "options"]
    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("pending") == "1":
            qs = qs.exclude(next_action="").exclude(mode="HUMANO").annotate(rank=Case(When(priority="Alta", then=Value(0)), When(priority="Média", then=Value(1)), default=Value(2), output_field=IntegerField())).order_by("rank", "return_at")
        return qs
    @action(detail=True)
    def events(self, request, pk=None):
        return Response(EventSerializer(self.get_object().events.all(), many=True).data)

class QuestionViewSet(TenantMixin, viewsets.ModelViewSet):
    queryset = Question.objects.all().order_by("id")
    serializer_class = QuestionSerializer
    def get_permissions(self):
        return [permissions.IsAuthenticated()] if self.request.method in permissions.SAFE_METHODS else [permissions.IsAdminUser()]
    def perform_create(self, serializer): serializer.save(company=self.company())
