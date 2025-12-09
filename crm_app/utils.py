import requests
from shapely.geometry import Point, Polygon
from .models import AreaVenda

def verificar_viabilidade_por_cep(cep):
    """
    Verifica se o CEP informado cai dentro de algum polígono de AreaVenda.
    1. Geocodifica o CEP para Lat/Long (Nominatim).
    2. Testa o ponto contra os polígonos salvos no banco.
    """
    # Remove caracteres não numéricos
    cep_limpo = "".join(filter(str.isdigit, str(cep)))
    
    # 1. Geocodificação (OpenStreetMap / Nominatim)
    # Docs: https://nominatim.org/release-docs/develop/api/Search/
    url = f"https://nominatim.openstreetmap.org/search?postalcode={cep_limpo}&country=Brazil&format=json"
    
    # User-Agent é obrigatório para a API do Nominatim não bloquear a requisição
    headers = {'User-Agent': 'RecordPAP-CRM/1.0 (interno)'}
    
    try:
        # Timeout de 5 segundos para não travar o sistema se a API demorar
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        
        if not data:
            return {
                'viabilidade': False, 
                'msg': 'CEP não localizado no mapa global (GPS).'
            }
            
        # Pega o primeiro resultado (mais provável)
        lat = float(data[0]['lat'])
        lon = float(data[0]['lon'])
        
        # Cria um ponto geométrico (Longitude, Latitude)
        # Atenção: Shapely usa ordem (x, y) que equivale a (lon, lat)
        ponto_endereco = Point(lon, lat) 
        
    except Exception as e:
        return {
            'viabilidade': False, 
            'msg': f"Erro ao consultar geolocalização: {str(e)}"
        }

    # 2. Verificar Polígonos no Banco de Dados
    # Filtra apenas áreas que possuem coordenadas cadastradas
    areas = AreaVenda.objects.exclude(coordenadas__isnull=True).exclude(coordenadas__exact='')
    
    area_encontrada = None
    
    for area in areas:
        try:
            # O formato salvo do KML geralmente é: "lon,lat,alt lon,lat,alt ..." (separado por espaço)
            coords_str = area.coordenadas.strip()
            coords_list = []
            
            # Processa a string de coordenadas para criar uma lista de tuplas (float, float)
            for c in coords_str.split(' '):
                parts = c.split(',')
                if len(parts) >= 2:
                    # KML usa (lon, lat)
                    coords_list.append((float(parts[0]), float(parts[1])))
            
            # Um polígono precisa de pelo menos 3 pontos
            if len(coords_list) < 3: 
                continue 
            
            # Cria o polígono com a biblioteca Shapely
            poligono = Polygon(coords_list)
            
            # Verifica se o ponto do CEP está dentro deste polígono
            if poligono.contains(ponto_endereco):
                area_encontrada = area
                break # Encontrou a área, para o loop
                
        except Exception as e:
            # Loga o erro no console mas continua verificando as outras áreas
            print(f"Erro ao calcular polígono da área ID {area.id}: {e}")
            continue

    # 3. Retorna o Resultado
    if area_encontrada:
        return {
            'viabilidade': True,
            'celula': area_encontrada.celula,
            'status': area_encontrada.status_venda,
            'municipio': area_encontrada.municipio,
            'cluster': area_encontrada.cluster,
            'hp_viavel': area_encontrada.hp_viavel,
            'msg': 'CEP com cobertura!'
        }
    else:
        return {
            'viabilidade': False,
            'msg': 'CEP localizado, mas fora da área de cobertura mapeada.'
        }