# presenca/serializers.py
from rest_framework import serializers
from .models import MotivoAusencia, Presenca, DiaNaoUtil

class MotivoAusenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = MotivoAusencia
        fields = '__all__'

class PresencaSerializer(serializers.ModelSerializer):
    colaborador_nome = serializers.CharField(source='colaborador.get_full_name', read_only=True)
    # --- CORREÇÃO APLICADA AQUI ---
    # Trocamos 'allow_nil' por 'allow_null'
    motivo_nome = serializers.CharField(source='motivo.motivo', read_only=True, allow_null=True)
    lancado_por_nome = serializers.CharField(source='lancado_por.get_full_name', read_only=True, allow_null=True)
    editado_por_nome = serializers.CharField(source='editado_por.get_full_name', read_only=True, allow_null=True)

    class Meta:
        model = Presenca
        fields = [
            'id', 'colaborador', 'colaborador_nome', 'data', 'status', 
            'motivo', 'motivo_nome', 'observacao', 
            'lancado_por', 'lancado_por_nome',
            'criado_em', 'editado_em', 'editado_por', 'editado_por_nome'
        ]

class DiaNaoUtilSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiaNaoUtil
        fields = '__all__'