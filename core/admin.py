from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import models


@admin.register(models.Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "nome_completo", "papel", "is_active", "deve_trocar_senha")
    list_filter = ("papel", "is_active")
    search_fields = ("username", "nome_completo", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("Estágio Monitor", {"fields": ("papel", "nome_completo", "telefone", "cpf", "matricula", "cargo", "concedentes", "foto",
                                   "cursos_coordenados", "deve_trocar_senha")}),
        ("Perfil profissional", {"fields": ("apresentacao", "habilidades", "curriculo", "perfil_visivel")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (("Estágio Monitor", {"fields": ("papel", "nome_completo")}),)


class EscalaInline(admin.TabularInline):
    model = models.Escala
    extra = 0


@admin.register(models.Turma)
class TurmaAdmin(admin.ModelAdmin):
    list_display = ("curso", "nome", "ano_ingresso", "ano_estagio", "ativa")
    list_filter = ("ano_estagio", "curso", "ativa")


@admin.register(models.FolhaEnviada)
class FolhaEnviadaAdmin(admin.ModelAdmin):
    list_display = ("mes", "turma", "nome_original", "enviado_por", "enviado_em")
    list_filter = ("mes",)
    filter_horizontal = ("estagios",)


@admin.register(models.HistoricoRegistro)
class HistoricoRegistroAdmin(admin.ModelAdmin):
    list_display = ("estagio", "data", "usuario", "acao", "em")
    list_filter = ("acao",)
    readonly_fields = [f.name for f in models.HistoricoRegistro._meta.fields]


@admin.register(models.TrocaSupervisor)
class TrocaSupervisorAdmin(admin.ModelAdmin):
    list_display = ("estagio", "anterior", "novo", "feita_por", "feita_em")


@admin.register(models.Estagio)
class EstagioAdmin(admin.ModelAdmin):
    list_display = ("estagiario", "curso", "turma", "local", "supervisor", "orientador", "data_inicio", "ativo")
    list_filter = ("curso", "turma__ano_estagio", "ativo", "orientador")
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


@admin.register(models.Justificativa)
class JustificativaAdmin(admin.ModelAdmin):
    list_display = ["estagio", "tipo", "data_inicio", "data_fim", "status", "criado_em", "decidido_por"]
    list_filter = ["status", "tipo"]
    search_fields = ["estagio__estagiario__nome_completo"]
    raw_id_fields = ["estagio", "enviado_por", "decidido_por"]


@admin.register(models.Comunicado)
class ComunicadoAdmin(admin.ModelAdmin):
    list_display = ["titulo", "autor", "para", "criado_em"]
    filter_horizontal = ["destinatarios"]


@admin.register(models.InscricaoPush)
class InscricaoPushAdmin(admin.ModelAdmin):
    list_display = ["usuario", "navegador", "criado_em", "ultimo_envio"]
    readonly_fields = ["usuario", "endpoint", "p256dh", "auth", "navegador", "criado_em", "ultimo_envio"]
