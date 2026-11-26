"""Formato ``jsonlp`` do dumpdata/loaddata: igual ao ``jsonl`` do Django, mas sem cortar os microssegundos.

O codificador JSON do Django corta datas e horas em milissegundos (``12:30:15.123456`` vira ``12:30:15.123``).
Na troca de banco isso alteraria todos os carimbos de data e hora, e a comparação dos bancos acusaria diferença.
Uso (ver docs/operacao/migracao-postgresql.md):

    python manage.py dumpdata --natural-foreign --exclude contenttypes --exclude auth.permission \\
        --format jsonlp -o /data/migracao/dados.jsonlp.gz
    python manage.py loaddata /data/migracao/dados.jsonlp.gz
"""
import datetime as dt

from django.core.serializers import jsonl
from django.core.serializers.json import DjangoJSONEncoder


class CodificadorPreciso(DjangoJSONEncoder):
    def default(self, o):
        if isinstance(o, dt.datetime):
            texto = o.isoformat()
            return texto[:-6] + "Z" if texto.endswith("+00:00") else texto
        if isinstance(o, dt.time):
            return o.isoformat()
        return super().default(o)


class Serializer(jsonl.Serializer):
    def _init_options(self):
        super()._init_options()
        self.json_kwargs["cls"] = CodificadorPreciso


Deserializer = jsonl.Deserializer
