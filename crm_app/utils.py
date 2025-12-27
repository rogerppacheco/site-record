import logging
import requests
import re
from django.db.models import Q
from .models import DFV, AreaVenda

logger = logging.getLogger(__name__)

def limpar_texto(texto):
    if not texto: return ""
    return ''.join(filter(str.isdigit, str(texto)))

def buscar_coordenadas_viacep(cep):
    """
    Converte CEP em Latitude/Longitude usando ViaCEP + OpenStreetMap (Nominatim)
    """
    try:
        # 1. Pega endereço do ViaCEP
        url_viacep = f"https://viacep.com.br/ws/{cep}/json/"
        resp = requests.get(url_viacep, timeout=5)
        if resp.status_code != 200: return None
        data = resp.json()
        if 'erro' in data: return None
        
        logradouro = data.get('logradouro')
        cidade = data.get('localidade')
        uf = data.get('uf')
        bairro = data.get('bairro')
        
        # Query de busca para o Geocoder
        query = f"{logradouro}, {cidade} - {uf}, Brasil"
        
        # 2. Geocodificação (Nominatim - OpenStreetMap)
        headers = {'User-Agent': 'RecordPAP_System/1.0'}
        url_geo = "https://nominatim.openstreetmap.org/search"
        params = {'q': query, 'format': 'json', 'limit': 1}
        
        resp_geo = requests.get(url_geo, params=params, headers=headers, timeout=5)
        if resp_geo.status_code == 200 and resp_geo.json():
            res = resp_geo.json()[0]
            return {
                'lat': float(res['lat']),
                'lng': float(res['lon']),
                'endereco_str': f"{logradouro}, {bairro} - {cidade}"
            }
            
    except Exception as e:
        print(f"Erro geocoding: {e}")
        pass
    
    return None

def verificar_viabilidade_por_cep(cep):
    """
    Função de compatibilidade (Legado).
    Algumas views antigas podem chamar essa função.
    """
    cep_limpo = limpar_texto(cep)
    # Busca simples na DFV pelo CEP (qualquer número)
    dfv = DFV.objects.filter(cep=cep_limpo).first()
    
    if dfv:
        return {
            'viavel': True,
            'msg': f"CEP {cep} consta na base DFV com status: {dfv.tipo_viabilidade}"
        }
    else:
        return {
            'viavel': False,
            'msg': f"CEP {cep} não localizado na base exata."
        }

def consultar_fachada_dfv(cep, numero):
    """
    Busca EXATA na base DFV (Fachada).
    """
    cep_limpo = limpar_texto(cep)
    numero_limpo = str(numero).strip().upper()

    print(f"\n🔎 BUSCA DFV (FACHADA) -> CEP: {cep_limpo} | NUM: {numero_limpo}")

    # Tenta busca exata (String)
    dfv = DFV.objects.filter(cep=cep_limpo, num_fachada=numero_limpo).first()
    
    # Se não achar, tenta converter número para int (tira zeros à esquerda ex: 0126 -> 126)
    if not dfv and numero_limpo.isdigit():
        num_int = str(int(numero_limpo))
        dfv = DFV.objects.filter(cep=cep_limpo, num_fachada=num_int).first()

    if dfv:
        tipo = dfv.tipo_viabilidade.upper() if dfv.tipo_viabilidade else ""
        rede = dfv.tipo_rede or "Desconhecida"
        
        if "VIAVEL" in tipo or "VIÁVEL" in tipo:
            return (
                f"✅ *FACHADA LOCALIZADA (DFV)*\n\n"
                f"O endereço consta na base DFV como *VIÁVEL*.\n"
                f"📍 *Endereço:* {dfv.logradouro}, {dfv.num_fachada}\n"
                f"🏙️ *Bairro:* {dfv.bairro}\n"
                f"📡 *Rede:* {rede}\n"
                f"📂 *Base:* DFV (Arquivo Importado)"
            )
        else:
            return (
                f"⚠️ *FACHADA NA BASE, MAS...*\n\n"
                f"Endereço encontrado na DFV, mas o status é: *{tipo}*.\n"
                f"Consulte seu supervisor."
            )
    else:
        return (
            f"❌ *FACHADA NÃO ENCONTRADA*\n\n"
            f"O CEP {cep_limpo} com número {numero_limpo} não consta na planilha de DFV importada.\n"
            f"Verifique se digitou o número corretamente."
        )

def consultar_viabilidade_kmz(cep):
    """
    Busca GEOGRÁFICA na base KMZ (AreaVenda).
    Converte CEP -> Lat/Lng -> Verifica se está na área.
    """
    cep_limpo = limpar_texto(cep)
    print(f"\n🔎 BUSCA KMZ (VIABILIDADE) -> CEP: {cep_limpo}")

    coords_data = buscar_coordenadas_viacep(cep_limpo)
    
    if not coords_data:
        return (
            f"❌ *CEP NÃO GEOLOCALIZADO*\n\n"
            f"Não conseguimos encontrar as coordenadas do CEP {cep_limpo} no mapa.\n"
            f"Por favor, tente enviar a *Localização (Pino)* do WhatsApp em vez do CEP."
        )

    lat = coords_data['lat']
    lng = coords_data['lng']
    endereco = coords_data['endereco_str']

    # Busca por texto (Bairro/Cidade) nas Áreas importadas
    partes = endereco.split(',')
    bairro_cep = ""
    if len(partes) >= 2:
        # Tenta extrair bairro grosseiramente
        bairro_cep = partes[1].split('-')[0].strip()

    print(f"📍 Coordenadas: {lat}, {lng} | Endereço: {endereco}")

    # Tenta achar uma Área de Venda que tenha esse bairro ou cidade
    area = AreaVenda.objects.filter(
        Q(bairro__icontains=bairro_cep) | 
        Q(nome_kml__icontains=bairro_cep)
    ).first()

    if area:
        return (
            f"✅ *VIABILIDADE (KMZ)*\n\n"
            f"O CEP {cep_limpo} está em uma região mapeada no KMZ!\n\n"
            f"🗺️ *Área:* {area.nome_kml}\n"
            f"🏙️ *Bairro/Cluster:* {area.bairro} / {area.cluster}\n"
            f"📊 *Status:* {area.status_venda or 'Liberado'}\n\n"
            f"_Obs: Validação baseada no cadastro do bairro/área no KMZ._"
        )
    else:
        return (
            f"❌ *FORA DE ÁREA (KMZ)*\n\n"
            f"O endereço localizado ({endereco}) não corresponde a nenhuma Área de Venda importada (KMZ).\n"
            f"Pode ser uma área nova ou sem cobertura."
        )

def verificar_viabilidade_por_coordenadas(lat, lng):
    """
    Chamado quando o usuário manda a localização (Pino).
    """
    return {'msg': f"📍 Recebemos sua localização ({lat}, {lng}). \nConsulte a base por CEP (Viabilidade) ou Endereço (Fachada)."}

def verificar_viabilidade_exata(cep, numero):
    """
    Função de compatibilidade. Redireciona para a nova fachada.
    """
    return {'msg': consultar_fachada_dfv(cep, numero)}