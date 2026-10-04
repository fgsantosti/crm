from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("crm", "0025_lead_urgencia_detalhe")]

    operations = [
        migrations.AddField(
            model_name="event",
            name="marker",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
