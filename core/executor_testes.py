"""Executor dos testes (``TEST_RUNNER``): o mesmo do Django, com a saída limpa.

Muitos testes conferem de propósito o acesso negado (403), a página inexistente (404), o pedido inválido (400), o
link expirado (410) e o backup sem chave. O Django registra cada um no log, com o rastro do erro, e a saída da suíte
ficava cheia de tracebacks que não são falhas. Erros do servidor (500) continuam aparecendo.

Também ficam de fora as mensagens só informativas (abaixo de WARNING).

O filtro vale só para o **console** e só durante os testes: os outros destinos do log (o aviso de erro aos
administradores, ``assertLogs``) continuam recebendo tudo. Qualquer outro erro continua aparecendo.
"""
import logging
import warnings

from django.test.runner import DiscoverRunner

MENSAGENS_ESPERADAS = ("Backup dos dados falhou",)


class LogsEsperadosNosTestes(logging.Filter):
    def filter(self, record):
        if record.levelno < logging.WARNING:  # informação (ex.: “Resumo semanal enviado”) não é falha
            return False
        if record.name.startswith("django.") and 400 <= (getattr(record, "status_code", None) or 0) < 500:
            return False  # “Forbidden (Permission denied)” com o PermissionDenied, “Not Found”, “Bad Request”, “Gone”
        return not (isinstance(record.msg, str) and record.msg.startswith(MENSAGENS_ESPERADAS))


class ExecutorDeTestes(DiscoverRunner):
    filtro = LogsEsperadosNosTestes()

    def _consoles(self):
        return [h for h in logging.getLogger().handlers
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        for h in self._consoles():
            h.addFilter(self.filtro)
        # o WhiteNoise avisa que a pasta do collectstatic não existe (nos testes ela nunca existe)
        warnings.filterwarnings("ignore", message="No directory at", category=UserWarning)

    def teardown_test_environment(self, **kwargs):
        for h in self._consoles():
            h.removeFilter(self.filtro)
        super().teardown_test_environment(**kwargs)
