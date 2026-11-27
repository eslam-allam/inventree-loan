from django.db import migrations


LEGACY_SETTINGS = {
    "PUBLIC_FIELD_PHONE": "phone",
    "PUBLIC_FIELD_ORGANIZATION": "organization",
    "PUBLIC_FIELD_IDENTIFIER": "student_employee_id",
    "PUBLIC_FIELD_PROJECT": "project_course",
}

FIELD_DEFINITIONS = [
    ("phone", "Phone", "phone", "PUBLIC_FIELD_PHONE", 10),
    (
        "organization",
        "Organization or department",
        "text",
        "PUBLIC_FIELD_ORGANIZATION",
        20,
    ),
    (
        "student_employee_id",
        "Student or employee ID",
        "text",
        "PUBLIC_FIELD_IDENTIFIER",
        30,
    ),
    (
        "project_course",
        "Project or course",
        "text",
        "PUBLIC_FIELD_PROJECT",
        40,
    ),
]


def forwards(apps, schema_editor):
    """Move legacy requester detail fields into active custom fields."""
    LoanRequest = apps.get_model("inventree_loan", "LoanRequest")
    LoanRequestCustomField = apps.get_model(
        "inventree_loan", "LoanRequestCustomField"
    )

    settings_values = {}
    PluginSetting = None
    try:
        PluginSetting = apps.get_model("plugin", "PluginSetting")
        settings_values = dict(
            PluginSetting.objects.filter(
                plugin__key="loan", key__in=LEGACY_SETTINGS
            ).values_list("key", "value")
        )
    except Exception:  # pragma: no cover - plugin app state may be unavailable
        PluginSetting = None

    has_requests = LoanRequest.objects.exists()

    # A fresh install has no requests and no legacy field settings. Do not
    # create university-specific fields in that case.
    if has_requests or settings_values:
        for key, label, field_type, setting_key, sort_order in FIELD_DEFINITIONS:
            required = (
                str(settings_values.get(setting_key, "")).strip().lower()
                == "required"
            )
            LoanRequestCustomField.objects.get_or_create(
                key=key,
                defaults={
                    "label": label,
                    "field_type": field_type,
                    "required": required,
                    "active": True,
                    "sort_order": sort_order,
                },
            )

        for loan_request in LoanRequest.objects.all().iterator():
            custom = dict(loan_request.custom_fields or {})
            changes = {
                "phone": loan_request.requester_phone or loan_request.contact,
                "organization": loan_request.requester_organization,
                "student_employee_id": loan_request.requester_identifier,
                "project_course": loan_request.project,
            }
            changed = False
            for key, value in changes.items():
                text = str(value or "").strip()
                if text and not custom.get(key):
                    custom[key] = text
                    changed = True
            if changed:
                LoanRequest.objects.filter(pk=loan_request.pk).update(
                    custom_fields=custom
                )

    if PluginSetting is not None:
        PluginSetting.objects.filter(
            plugin__key="loan", key__in=LEGACY_SETTINGS
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("inventree_loan", "0007_loanrequestcustomfield_loanrequest_custom_fields"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
