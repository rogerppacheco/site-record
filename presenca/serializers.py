# site-record/presenca/serializers.py

from rest_framework import serializers
from .models import MotivoAusencia, Presenca, DiaNaoUtil

class MotivoAusenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = MotivoAusencia
        fields = '__all__'

class DiaNaoUtilSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiaNaoUtil
        fields = '__all__'

class PresencaSerializer(serializers.ModelSerializer):
    # MUDANÇA: source='....username' pega o login em vez do nome
    colaborador_nome = serializers.CharField(source='colaborador.username', read_only=True)
    motivo_nome = serializers.CharField(source='motivo.motivo', read_only=True)
    lancado_por_nome = serializers.CharField(source='lancado_por.username', read_only=True)
    editado_por_nome = serializers.CharField(source='editado_por.username', read_only=True)

    class Meta:
        model = Presenca
        fields = '__all__'