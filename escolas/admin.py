"""O /admin/ do Django é só do administrador da plataforma (técnico). Nele, a plataforma vê todas as escolas.

Cadastro de escolas, redes e vínculos. As telas da gestão escolar continuam no sistema (o administrador da escola
não entra aqui)."""
from django.contrib import admin

from .models import Escola, RedeEnsino, VinculoEscola


def so_plataforma(request):
    user = request.user
    return bool(user.is_active and user.is_staff and getattr(user, "administrador_plataforma", False))


admin.site.has_permission = so_plataforma
admin.site.site_header = "Estágio Monitor · plataforma"


@admin.register(RedeEnsino)
class RedeEnsinoAdmin(admin.ModelAdmin):
    list_display = ("nome", "uf", "secretaria", "sistema_oficial")
    search_fields = ("nome", "secretaria")


class VinculoInline(admin.TabularInline):
    model = VinculoEscola
    extra = 0
    autocomplete_fields = ("usuario",)
    fields = ("usuario", "papel", "ativo", "inicio", "fim")


@admin.register(Escola)
class EscolaAdmin(admin.ModelAdmin):
    list_display = ("nome", "slug", "municipio", "uf", "situacao", "rede")
    list_filter = ("situacao", "rede")
    search_fields = ("nome", "codigo_inep", "municipio")
    prepopulated_fields = {"slug": ("nome",)}

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            from core.models import Configuracao

            Configuracao.objects.get_or_create(escola=obj)  # escola nova já nasce com a configuração própria


@admin.register(VinculoEscola)
class VinculoEscolaAdmin(admin.ModelAdmin):
    list_display = ("usuario", "escola", "papel", "ativo", "inicio", "fim")
    list_filter = ("escola", "papel", "ativo")
    search_fields = ("usuario__nome_completo", "usuario__username")
    autocomplete_fields = ("usuario",)
