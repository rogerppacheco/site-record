import requests
import logging
from shapely.geometry import Point, Polygon

logger = logging.getLogger(__name__)

def verificar_viabilidade_por_coordenadas(lat, lon):
    """
    Verifica se a coordenada cai dentro (ou muito perto) de algum polígono cadastrado (AreaVenda).
    """
    # Importação local para evitar Ciclo de Importação (Circular Import) com models.py
    from .models import AreaVenda 
    
    ponto_endereco = Point(lon, lat) 
    
    # Filtra apenas áreas com coordenadas cadastradas
    areas = AreaVenda.objects.exclude(coordenadas__isnull=True).exclude(coordenadas__exact='')
    
    area_encontrada = None
    distancia_minima = 1000 # Começa alto
    
    # Tolerância de aprox. 30 metros (0.0003 graus)
    # Isso resolve o problema do "Pino no meio da rua" vs "Polígono na calçada"
    TOLERANCIA = 0.0003 
    
    for area in areas:
        try:
            coords_str = area.coordenadas.strip()
            coords_list = []
            
            # Parse KML (lon,lat) - O formato padrão KML é longitude,latitude
            for c in coords_str.split(' '):
                parts = c.split(',')
                if len(parts) >= 2:
                    coords_list.append((float(parts[0]), float(parts[1])))
            
            if len(coords_list) < 3: continue 
            
            poligono = Polygon(coords_list)
            
            # 1. Verifica se está DENTRO (Exato)
            if poligono.contains(ponto_endereco):
                area_encontrada = area
                break 
            
            # 2. Verifica se está PERTO (Tolerância)
            dist = poligono.distance(ponto_endereco)
            if dist < TOLERANCIA and dist < distancia_minima:
                area_encontrada = area
                distancia_minima = dist
                # Não damos break aqui para tentar achar uma mais perto (exata) depois
                
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
    Busca pelo CENTRO do CEP (Fallback).
    """
    cep_limpo = "".join(filter(str.isdigit, str(cep)))
    # Usa postalcode + country para evitar ambiguidade
    url = f"https://nominatim.openstreetmap.org/search?postalcode={cep_limpo}&country=Brazil&format=json"
    
    # Adiciona aviso na mensagem se for busca genérica
    resultado = _executar_busca_nominatim(url)
    if resultado['viabilidade']:
        resultado['msg'] = "⚠️ *Atenção:* Número não localizado, validado pelo *centro do CEP*.\n\n" + resultado['msg']
    return resultado

def verificar_viabilidade_exata(cep, numero):
    """
    Tenta busca exata (Rua + Número + CEP). Se falhar, busca automaticamente pelo CEP.
    """
    cep_limpo = "".join(filter(str.isdigit, str(cep)))
    
    # Tenta buscar: Rua, Número, CEP (countrycodes=br para evitar erro 400)
    query = f"{numero}, {cep_limpo}"
    url = f"https://nominatim.openstreetmap.org/search?q={query}&countrycodes=br&format=json&limit=1"
    
    resultado = _executar_busca_nominatim(url, eh_exata=True)
    
    # --- FALLBACK AUTOMÁTICO ---
    # Se a busca exata falhou (não achou o número ou deu erro), tenta só o CEP
    if not resultado['viabilidade']:
        return verificar_viabilidade_por_cep(cep_limpo)
        
    return resultado

def _executar_busca_nominatim(url, eh_exata=False):
    """
    Função auxiliar interna para chamar a API do Nominatim e processar o JSON.
    """
    headers = {'User-Agent': 'RecordPAP-CRM/1.0'}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        
        try:
            data = response.json()
        except ValueError:
            return {'viabilidade': False, 'msg': 'Erro técnico no mapa (JSON inválido).'}
        
        # Se for erro da API (dicionário com chave error)
        if isinstance(data, dict) and ('error' in data or 'message' in data):
             return {'viabilidade': False, 'msg': 'Erro na comunicação com o mapa.'}

        # Se não achou nada (lista vazia)
        if not data or (isinstance(data, list) and len(data) == 0):
            if eh_exata:
                # Retorna erro específico para acionar o fallback
                return {'viabilidade': False, 'erro_busca': True, 'msg': 'Número não localizado.'}
            return {'viabilidade': False, 'msg': 'CEP não localizado no mapa.'}
        
        # Pega o primeiro resultado da lista
        item = data[0] if isinstance(data, list) else data

        lat = float(item.get('lat', 0))
        lon = float(item.get('lon', 0))
        
        if lat == 0 or lon == 0:
             return {'viabilidade': False, 'msg': 'Coordenadas inválidas recebidas do mapa.'}
        
        # Chama a função geométrica principal
        return verificar_viabilidade_por_coordenadas(lat, lon)
        
    except Exception as e:
        return {'viabilidade': False, 'msg': f"Erro técnico ao consultar mapa: {str(e)}"}