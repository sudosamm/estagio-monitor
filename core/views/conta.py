"""Conta sem estar logado: esqueci a senha (link por e-mail) e pedido de ajuda ao administrador."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordResetConfirmView
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlencode, urlsafe_base64_encode
from django.views.decorators.cache import never_cache

from .. import emails
from ..forms import EsqueciSenhaForm, PedidoAjudaForm
from ..models import Notificacao, Usuario
from ..seguranca import excedeu, ip_de, limpar, registrar_pedido

PREFIXO_SENHA, PREFIXO_AJUDA = "senha:", "ajuda:"


def _contas_do_identificador(texto):
    texto = texto.strip()
    qs = Usuario.objects.filter(is_active=True, email_confirmado_em__isnull=False, anonimizado_em__isnull=True)
    return list(qs.filter(email__iexact=texto) if "@" in texto else qs.filter(username__iexact=texto).exclude(email=""))


@never_cache
def esqueci_senha(request):
    if request.user.is_authenticated:
        return redirect("trocar_senha")
    form = EsqueciSenhaForm(request.POST or None)
    enviado = False
    if request.method == "POST" and form.is_valid() and settings.EMAIL_ATIVO:
        texto, ip = form.cleaned_data["identificador"], ip_de(request)
        enviado = True  # a resposta é sempre a mesma: não revela se a conta existe
        if not excedeu(PREFIXO_SENHA, texto, ip, por_chave=3, por_ip=10):
            registrar_pedido(PREFIXO_SENHA, texto, ip)
            for user in _contas_do_identificador(texto):
                caminho = reverse("redefinir_senha_email", args=[urlsafe_base64_encode(force_bytes(user.pk)),
                                                                 default_token_generator.make_token(user)])
                emails.enviar("REDEFINIR_SENHA", [user.email], nome=user.primeiro_nome, usuario=user.username,
                              link=emails.endereco(request, caminho), validade="2 horas", quando=emails.quando(),
                              ip=ip or "desconhecido")
    return render(request, "registration/esqueci_senha.html", {"form": form, "enviado": enviado})


class RedefinirSenhaView(PasswordResetConfirmView):
    """Link do e-mail. O Django tira o código da URL (guarda na sessão) antes de mostrar o formulário."""

    template_name = "registration/redefinir_senha.html"
    success_url = reverse_lazy("login")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for f in form.fields.values():
            f.help_text = ""
        return form

    def form_valid(self, form):
        resposta = super().form_valid(form)
        user = self.user
        user.deve_trocar_senha = False
        user.codigo_acesso, user.codigo_acesso_validade = "", None
        user.save(update_fields=["deve_trocar_senha", "codigo_acesso", "codigo_acesso_validade"])
        limpar(user.username)  # desbloqueia o login, se estava bloqueado
        from ..sessoes import desconectar_todas

        desconectar_todas(user)  # quem estava conectado com a senha antiga sai
        emails.avisar_senha_alterada(self.request, user)
        messages.success(self.request, f"Senha nova criada. Entre com o usuário {user.username} e a senha nova.")
        return resposta


@never_cache
def pedir_ajuda(request):
    form = PedidoAjudaForm(request.POST or None, initial={"usuario": request.GET.get("usuario", "")[:150]})
    if request.method == "POST" and form.is_valid():
        d, ip = form.cleaned_data, ip_de(request)
        if d["site"]:  # robô
            return render(request, "registration/pedir_ajuda.html", {"enviado": True})
        if excedeu(PREFIXO_AJUDA, "", ip, por_chave=0, por_ip=3):
            form.add_error(None, "Você já mandou alguns pedidos. Aguarde a resposta ou tente de novo daqui a uma hora.")
        else:
            registrar_pedido(PREFIXO_AJUDA, d["usuario"] or d["nome"], ip)
            admins = list(Usuario.objects.filter(is_superuser=True, is_active=True))
            link = (reverse("usuarios") + (f"?{urlencode({'q': d['usuario']})}" if d["usuario"] else ""))[:255]
            texto = f"Pedido de ajuda com o acesso: {d['nome']}" + (f" ({d['usuario']})" if d["usuario"] else "")
            Notificacao.objects.bulk_create([Notificacao(usuario=a, link=link, texto=texto[:255]) for a in admins])
            emails.enviar("PEDIDO_AJUDA", [a.email for a in admins], usuario=d["usuario"] or "(não informado)",
                          nome=d["nome"], contato=d["contato"], mensagem=d["mensagem"], quando=emails.quando(),
                          ip=ip or "desconhecido", link=emails.endereco(request, link))
            return render(request, "registration/pedir_ajuda.html", {"enviado": True})
    return render(request, "registration/pedir_ajuda.html", {"form": form})
