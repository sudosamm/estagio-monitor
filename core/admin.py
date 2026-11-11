from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import models


@admin.register(models.Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "nome_completo", "papel", "local", "is_active", "deve_trocar_senha")
    list_filter = ("papel", "is_active")
    search_fields = ("username", "nome_completo", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("Estágio Monitor", {"fields": ("papel", "nome_completo", "telefone", "cpf", "matricula", "cargo", "local", "foto",
                                   "cursos_coordenados", "deve_trocar_senha")}),
        ("Perfil profissional", {"fields": ("apresentacao", "habilidades", "curriculo", "perfil_visivel")}),
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


@admin.register(models.ImpressaoFrequencia)
class ImpressaoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "estagio", "usuario", "mes", "aberta_em", "impressoes", "ultima_impressao")
    search_fields = ("codigo", "estagio__estagiario__nome_completo")
    list_filter = ("mes",)


class VagaInline(admin.TabularInline):
    model = models.VagaCandidatura
    extra = 0


@admin.register(models.Candidatura)
class CandidaturaAdmin(admin.ModelAdmin):
    list_display = ("nome", "ano", "status", "contato_nome", "contato_telefone", "criado_em")
    list_filter = ("ano", "status")
    search_fields = ("nome", "razao_social", "cnpj", "protocolo")
    inlines = [VagaInline]


for m in (models.AvisoExterno, models.Curso, models.LocalEstagio, models.DiaSemEstagio, models.Agendamento, models.DiaPlanejado,
          models.Documento, models.Mensagem, models.Notificacao, models.Configuracao):
    admin.site.register(m)
