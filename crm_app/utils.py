import logging
import requests
import re
from django.db.models import Q
from .models import DFV, AreaVenda

logger = logging.getLogger(__name__)

def limpar_texto(texto):
    if not texto: return ""
    return ''.join(filter(str.isdigit, str(texto)))

def buscar_coordenadas_viacep_nominatim(cep, numero):
    """
    Busca Lat/Lng usando o CEP para achar a rua e o Número para precisão.
    """
    try:
        # 1. Pega dados da Rua pelo ViaCEP
        url_viacep = f"https://viacep.com.br/ws/{cep}/json/"
        resp = requests.get(url_viacep, timeout=5)
        if resp.status_code != 200: return None
        data = resp.json()
        if 'erro' in data: return None
        
        logradouro = data.get('logradouro')
        cidade = data.get('localidade')
        uf = data.get('uf')
        bairro = data.get('bairro')
        
        # 2. Monta Query para OpenStreetMap (Nominatim)
        # Ex: "Rua das Flores, 123, Belo Horizonte - MG, Brasil"
        query = f"{logradouro}, {numero}, {cidade} - {uf}, Brasil"
        
        headers = {'User-Agent': 'RecordPAP_System/2.0'}
        url_geo = "https://nominatim.openstreetmap.org/search"
        # O '1' no limit tenta pegar o mais preciso
        params = {'q': query, 'format': 'json', 'limit': 1}
        
        resp_geo = requests.get(url_geo, params=params, headers=headers, timeout=5)
        
        # Se não achar com número, tenta só com a rua (menos preciso, mas serve de fallback)
        if not resp_geo.json():
            query_fallback = f"{logradouro}, {cidade} - {uf}, Brasil"
            params['q'] = query_fallback
            resp_geo = requests.get(url_geo, params=params, headers=headers, timeout=5)

        if resp_geo.status_code == 200 and resp_geo.json():
            res = resp_geo.json()[0]
            return {
                'lat': float(res['lat']),
                'lng': float(res['lon']),
                'endereco_str': f"{logradouro}, {numero} - {bairro}",
                'cidade': cidade,
                'bairro': bairro
            }
            
    except Exception as e:
        print(f"Erro geocoding: {e}")
    
    return None

def ponto_dentro_poligono(x, y, poligono):
    """
    Algoritmo Ray Casting para verificar se ponto (x,y) está dentro do polígono.
    x = lng, y = lat
    poligono = lista de tuplas [(lng, lat), (lng, lat)...]
    """
    n = len(poligono)
    inside = False
    p1x, p1y = poligono[0]
    for i in range(n + 1):
        p2x, p2y = poligono[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def parse_kml_coordinates(coords_str):
    """
    Transforma string do KML "lon,lat,z lon,lat,z" em lista de tuplas [(lon, lat)]
    """
    pontos = []
    if not coords_str: return []
    
    # KML separa por espaço ou quebra de linha
    items = coords_str.replace('\n', ' ').split(' ')
    for item in items:
        if not item: continue
        parts = item.split(',')
        if len(parts) >= 2:
            try:
                # KML é (Longitude, Latitude)
                lon = float(parts[0])
                lat = float(parts[1])
                pontos.append((lon, lat))
            except: pass
    return pontos

# --- FUNÇÕES DE CONSULTA ---

def consultar_fachada_dfv(cep, numero):
    cep_limpo = limpar_texto(cep)
    numero_limpo = str(numero).strip().upper()
    print(f"\n🔎 BUSCA DFV (FACHADA) -> CEP: {cep_limpo} | NUM: {numero_limpo}")

    dfv = DFV.objects.filter(cep=cep_limpo, num_fachada=numero_limpo).first()
    if not dfv and numero_limpo.isdigit():
        dfv = DFV.objects.filter(cep=cep_limpo, num_fachada=str(int(numero_limpo))).first()

    if dfv:
        tipo = dfv.tipo_viabilidade.upper() if dfv.tipo_viabilidade else ""
        return f"✅ *FACHADA LOCALIZADA (DFV)*\nStatus: *{tipo}*\nEnd: {dfv.logradouro}, {dfv.num_fachada}"
    else:
        return f"❌ *FACHADA NÃO ENCONTRADA*\nO número {numero_limpo} no CEP {cep_limpo} não consta na base DFV."

def consultar_viabilidade_kmz(cep, numero):
    """
    Lógica Completa: CEP+Num -> Lat/Lng -> Verifica Polígono
    """
    cep_limpo = limpar_texto(cep)
    print(f"\n🔎 BUSCA KMZ (GEO) -> CEP: {cep_limpo} | NUM: {numero}")

    # 1. Obter Coordenadas
    geo_data = buscar_coordenadas_viacep_nominatim(cep_limpo, numero)
    
    if not geo_data:
        return "❌ *ENDEREÇO NÃO LOCALIZADO*\nNão conseguimos converter esse CEP e número em coordenadas GPS. Tente enviar a localização (pino)."

    cliente_lat = geo_data['lat']
    cliente_lng = geo_data['lng']
    print(f"📍 Cliente está em: {cliente_lat}, {cliente_lng}")

    # 2. Filtrar Áreas Prováveis (Pelo Bairro ou Cidade para não varrer tudo)
    # Isso otimiza a busca. Pegamos areas que tenham o nome da cidade ou bairro.
    areas_candidatas = AreaVenda.objects.filter(
        Q(municipio__icontains=geo_data['cidade']) | 
        Q(bairro__icontains=geo_data['bairro']) |
        Q(nome_kml__icontains=geo_data['bairro'])
    )
    
    # Se não achar por bairro/cidade, pega tudo (pode ser lento se tiver milhares)
    if not areas_candidatas.exists():
        print("⚠️ Bairro/Cidade não bateu com KMZ, verificando todas as áreas...")
        areas_candidatas = AreaVenda.objects.all()

    # 3. Teste Matemático (Ponto dentro do Polígono)
    for area in areas_candidatas:
        # Transforma texto do banco em lista de pontos
        poligono = parse_kml_coordinates(area.coordenadas)
        if not poligono: continue
        
        # Testa
        if ponto_dentro_poligono(cliente_lng, cliente_lat, poligono):
            return (
                f"✅ *VIABILIDADE TÉCNICA (KMZ)*\n\n"
                f"O endereço está DENTRO da área de cobertura!\n"
                f"🗺️ *Área/Cluster:* {area.nome_kml}\n"
                f"🏙️ *Bairro:* {area.bairro}\n"
                f"📍 *Local:* {geo_data['endereco_str']}\n\n"
                f"⚠️ _Sujeito a vistoria técnica local._"
            )

    return (
        f"❌ *FORA DA MANCHA (KMZ)*\n\n"
        f"O endereço foi localizado no mapa, mas as coordenadas ({cliente_lat}, {cliente_lng}) caem FORA das áreas cadastradas no sistema.\n"
        f"📍 *Local:* {geo_data['endereco_str']}"
    )

def verificar_viabilidade_por_coordenadas(lat, lng):
    # Fallback para o pino
    return {'msg': f"📍 Recebido ({lat}, {lng}). Use a opção de CEP para validação precisa."}

# Compatibilidade
def verificar_viabilidade_por_cep(cep): return {'msg': 'Use a nova busca.'}
def verificar_viabilidade_exata(cep, num): return {'msg': consultar_fachada_dfv(cep, num)}