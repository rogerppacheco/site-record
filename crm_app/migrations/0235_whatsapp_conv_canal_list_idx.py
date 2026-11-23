from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0234_whatsapp_reply_canal_fase7"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="whatsappconversation",
            index=models.Index(
                fields=["channel", "reply_canal", "status", "-last_message_at"],
                name="crm_wa_conv_ch_rc_st_idx",
            ),
        ),
    ]
