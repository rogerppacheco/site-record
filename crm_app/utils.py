import requests
import logging
from shapely.geometry import Point, Polygon

logger = logging.getLogger(__name__)

def verificar_viabilidade_por_coordenadas(lat, lon):
    """
    Função matemática pura: Verifica se a coordenada cai dentro de algum polígono.
    """
    # Importação feita AQUI DENTRO para corrigir o erro "ImportError"
    from .models import AreaVenda 
    
    ponto_endereco = Point(lon, lat) 
    
    # Filtra apenas áreas com coordenadas cadastradas
    areas = AreaVenda.objects.exclude(coordenadas__isnull=True).exclude(coordenadas__exact='')
    
    area_encontrada = None
    
    for area in areas:
        try:
            coords_str = area.coordenadas.strip()
            coords_list = []
            
            # KML geralmente é: "lon,lat,alt lon,lat,alt"
            for c in coords_str.split(' '):
                parts = c.split(',')
                if len(parts) >= 2:
                    coords_list.append((float(parts[0]), float(parts[1])))
            
            if len(coords_list) < 3: 
                continue 
            
            poligono = Polygon(coords_list)
            
            if poligono.contains(ponto_endereco):
                area_encontrada = area
                break 
                
        except Exception as e:
            continue

    if area_encontrada:
        return {
            'viabilidade': True,
            'celula': area_encontrada.celula,
            'status': area_encontrada.status_venda,
            'municipio': area_encontrada.municipio,
            'cluster': area_encontrada.cluster,
            'hp_viavel': area_encontrada.hp_viavel,
            'msg': (
                f"✅ *COBERTURA ENCONTRADA!*\n\n"
                f"📍 *Célula:* {area_encontrada.celula}\n"
                f"📊 *Status:* {area_encontrada.status_venda}\n"
                f"🏙 *Município:* {area_encontrada.municipio}\n"
                f"🏠 *HP Viável:* {area_encontrada.hp_viavel}"
            )
        }
    else:
        return {
            'viabilidade': False,
            'msg': '📍 Localização recebida, mas está *FORA* da área de cobertura mapeada.'
        }

def verificar_viabilidade_por_cep(cep):
    """
    Busca pelo CENTRO do CEP (menos preciso).
    Usa parâmetros estruturados (postalcode), então PODE usar country.
    """
    cep_limpo = "".join(filter(str.isdigit, str(cep)))
    url = f"https://nominatim.openstreetmap.org/search?postalcode={cep_limpo}&country=Brazil&format=json"
    return _executar_busca_nominatim(url)

def verificar_viabilidade_exata(cep, numero):
    """
    Busca por Rua + Número + CEP (mais preciso).
    Usa parâmetro livre (q), então NÃO pode usar country (usamos countrycodes).
    """
    cep_limpo = "".join(filter(str.isdigit, str(cep)))
    query = f"{numero}, {cep_limpo}"
    # CORREÇÃO: Trocamos 'country=Brazil' por 'countrycodes=br' para evitar o erro 400
    url = f"https://nominatim.openstreetmap.org/search?q={query}&countrycodes=br&format=json&limit=1"
    return _executar_busca_nominatim(url, eh_exata=True)

def _executar_busca_nominatim(url, eh_exata=False):
    """
    Função auxiliar para consultar a API de mapas
    """
    headers = {'User-Agent': 'RecordPAP-CRM/1.0'}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        
        # Tenta ler o JSON
        try:
            data = response.json()
        except ValueError:
            return {'viabilidade': False, 'msg': 'Erro ao ler resposta do mapa (JSON inválido).'}
        
        # Se vier dicionário de erro (como o code 400 que você recebeu)
        if isinstance(data, dict) and 'error' in data:
             # Se for erro de parâmetro, retornamos msg técnica para debug
             if 'message' in data:
                 return {'viabilidade': False, 'msg': f"Erro na API de Mapa: {data.get('message')}"}
             return {'viabilidade': False, 'msg': f"Erro na API de Mapa: {data.get('error')}"}

        # Proteção contra lista vazia (não achou nada)
        if not data or (isinstance(data, list) and len(data) == 0):
            if eh_exata:
                return {'viabilidade': False, 'erro_busca': True, 'msg': 'Número não localizado.'}
            return {'viabilidade': False, 'msg': 'CEP não localizado no mapa.'}
        
        # Pega o primeiro item da lista com segurança
        if isinstance(data, list):
            item = data[0]
        else:
            item = data

        # Pega a lat/long
        lat = float(item.get('lat', 0))
        lon = float(item.get('lon', 0))
        
        if lat == 0 or lon == 0:
             return {'viabilidade': False, 'msg': 'Coordenadas inválidas recebidas.'}
        
        # Chama a função de geometria que criamos acima
        return verificar_viabilidade_por_coordenadas(lat, lon)
        
    except Exception as e:
        logger.error(f"Erro Busca Mapa: {e}")
        return {'viabilidade': False, 'msg': f"Erro técnico na busca: {str(e)}"}