# presenca/serializers.py
from rest_framework import serializers
from .models import MotivoAusencia, Presenca, DiaNaoUtil

class MotivoAusenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = MotivoAusencia
        fields = ['id', 'motivo', 'gera_desconto']

class PresencaSerializer(serializers.ModelSerializer):
    colaborador_nome = serializers.CharField(source='colaborador.get_full_name', read_only=True, allow_null=True)
    lancado_por_nome = serializers.SerializerMethodField()
    motivo_nome = serializers.CharField(source='motivo.motivo', read_only=True, allow_null=True)

    class Meta:
        model = Presenca
        fields = [
            'id', 'colaborador', 'colaborador_nome', 'data', 
            'motivo', 'motivo_nome', 'observacao', 'status', 
            'lancado_por', 'lancado_por_nome'
        ]
        # --- O ERRO ESTAVA AQUI ---
        # A linha 'write_only' foi removida para que a API sempre retorne o ID do colaborador.
        # O bloco extra_kwargs foi completamente removido.

    def get_lancado_por_nome(self, obj):
        if obj.lancado_por:
            full_name = obj.lancado_por.get_full_name()
            return full_name if full_name.strip() else obj.lancado_por.username
        return "Sistema"

class DiaNaoUtilSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiaNaoUtil
        fields = ['id', 'data', 'descricao']