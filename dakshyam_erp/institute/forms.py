from django import forms
from .models import StudentAdmission, FeeReceipt

class TailwindFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base_input = (
            "w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm "
            "text-slate-900 placeholder-slate-400 focus:border-indigo-500 "
            "focus:outline-none focus:ring-2 focus:ring-indigo-500/20 transition"
        )
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({
                    "class": "h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                })
            elif isinstance(field.widget, forms.FileInput):
                field.widget.attrs.update({
                    "class": "block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 "
                             "file:rounded-xl file:border-0 file:text-xs file:font-semibold "
                             "file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
                })
            else:
                field.widget.attrs.update({"class": base_input})


class AdmissionForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = StudentAdmission
        fields = [
            "full_name", "guardian_name", "phone", "whatsapp_no", "email",
            "school_or_college", "grade_or_year", "address", "photo",
            "course", "batch_timing", "discount_amount", "admission_date", "kit_issued"
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2, "placeholder": "Ward / Village, Waraseoni, Balaghat"}),
            "admission_date": forms.DateInput(attrs={"type": "date"}),
            "full_name": forms.TextInput(attrs={"placeholder": "e.g., Aarav Sharma"}),
            "guardian_name": forms.TextInput(attrs={"placeholder": "Parent / Guardian Full Name"}),
            "phone": forms.TextInput(attrs={"placeholder": "10-digit mobile number"}),
            "whatsapp_no": forms.TextInput(attrs={"placeholder": "Same as phone if blank"}),
            "school_or_college": forms.TextInput(attrs={"placeholder": "e.g., Sardar Patel University / Kendriya Vidyalaya"}),
            "grade_or_year": forms.TextInput(attrs={"placeholder": "e.g., Class 10 / B.Tech 2nd Year"}),
        }


class FeeReceiptForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = FeeReceipt
        fields = ["amount_paid", "payment_mode", "transaction_ref", "next_due_date", "remarks"]
        widgets = {
            "next_due_date": forms.DateInput(attrs={"type": "date"}),
            "transaction_ref": forms.TextInput(attrs={"placeholder": "UPI Ref ID / UTR / Cheque No."}),
            "remarks": forms.TextInput(attrs={"placeholder": "e.g., 1st Installment + Robotics Kit"}),
        }