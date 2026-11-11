from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import models


@admin.register(models.Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "nome_completo", "papel", "local", "is_active", "deve_trocar_senha")
    list_filter = ("papel", "is_active")
    search_fields = ("username", "nome_completo", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("Estágio Monitor", {"fields": ("papel", "nome_completo", "telefone", "matricula", "cargo", "local", "deve_trocar_senha")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (("Estágio Monitor", {"fields": ("papel", "nome_completo")}),)


class EscalaInline(admin.TabularInline):
    model = models.Escala
    extra = 0


@admin.register(models.Estagio)
class EstagioAdmin(admin.ModelAdmin):
    list_display = ("estagiario", "curso", "local", "supervisor", "orientador", "data_inicio", "ativo")
    list_filter = ("curso", "ativo", "orientador")
    search_fields = ("estagiario__nome_completo", "local__nome")
    inlines = [EscalaInline]


@admin.register(models.Registro)
class RegistroAdmin(admin.ModelAdmin):
    list_display = ("estagio", "data", "situacao", "horas", "confirmacao")
    list_filter = ("situacao", "confirmacao")
    date_hierarchy = "data"


for m in (models.Curso, models.LocalEstagio, models.DiaSemEstagio, models.Agendamento,
          models.Documento, models.Mensagem, models.Notificacao):
    admin.site.register(m)
