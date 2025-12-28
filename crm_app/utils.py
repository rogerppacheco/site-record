import logging
import requests
import re
from django.db.models import Q
from .models import DFV, AreaVenda
from .models import Venda # Certifique-se que Venda está importado

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
    """
    Busca EXATA na base DFV (Fachada). (Legado/Compatibilidade)
    Essa função valida um número específico se necessário.
    """
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

def listar_fachadas_dfv(cep):
    """
    Busca TODAS as fachadas (números) disponíveis para um CEP na base DFV.
    """
    cep_limpo = limpar_texto(cep)
    print(f"\n🔎 LISTAR FACHADAS DFV -> CEP: {cep_limpo}")

    # Busca todos os registros com esse CEP que sejam VIÁVEIS
    fachadas = DFV.objects.filter(
        cep=cep_limpo
    ).filter(
        Q(tipo_viabilidade__icontains='VIAVEL') | Q(tipo_viabilidade__icontains='VIÁVEL')
    ).values_list('num_fachada', 'logradouro', 'bairro', 'tipo_rede')

    if not fachadas:
        return (
            f"❌ *NENHUMA FACHADA ENCONTRADA*\n\n"
            f"Não encontramos nenhum número viável cadastrado na base DFV para o CEP {cep_limpo}.\n"
            f"Tente a consulta de *Viabilidade (KMZ)* para ver se a região tem cobertura."
        )

    # Pega dados do logradouro do primeiro resultado para cabeçalho
    exemplo = fachadas[0]
    logradouro = exemplo[1] or "Rua Desconhecida"
    bairro = exemplo[2] or "Bairro Desconhecido"
    tecnologia = exemplo[3] or "-"

    # Extrai e ordena os números
    # Tenta ordenar numericamente, se falhar ordena como texto (ex: 10, 100, 2)
    numeros = [f[0] for f in fachadas if f[0]]
    try:
        numeros.sort(key=lambda x: int(''.join(filter(str.isdigit, x))) if any(c.isdigit() for c in x) else 0)
    except:
        numeros.sort()

    total = len(numeros)
    lista_str = ", ".join(numeros)

    # Se a lista for muito grande, corta para não travar o Zap
    if len(lista_str) > 3000:
        lista_str = lista_str[:3000] + "... (lista muito longa)"

    return (
        f"🏢 *RELATÓRIO DE FACHADAS (DFV)*\n\n"
        f"📍 *Endereço:* {logradouro}\n"
        f"🏙️ *Bairro:* {bairro}\n"
        f"📡 *Tecnologia:* {tecnologia}\n"
        f"✅ *Total Viáveis:* {total}\n\n"
        f"🔢 *Números Disponíveis:*\n"
        f"{lista_str}"
    )

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
def consultar_status_venda(tipo_busca, valor):
    """
    Busca a última venda baseada em CPF ou OS e retorna os status.
    tipo_busca: 'CPF' ou 'OS'
    """
    valor_limpo = limpar_texto(valor) # Remove pontos e traços
    print(f"\n🔎 BUSCA STATUS ({tipo_busca}) -> Valor: {valor_limpo}")

    venda = None

    if tipo_busca == 'CPF':
        # Busca pela venda mais recente desse CPF (ordena por ID decrescente ou data)
        # Nota: cliente__cpf_cnpj é o campo de busca no relacionamento
        venda = Venda.objects.filter(
            cliente__cpf_cnpj__icontains=valor_limpo, 
            ativo=True
        ).order_by('-data_criacao').first()

    elif tipo_busca == 'OS':
        # Busca exata pela OS
        venda = Venda.objects.filter(
            ordem_servico=valor_limpo, 
            ativo=True
        ).first()

    if venda:
        # Formata os dados para exibir
        cliente_nome = venda.cliente.nome_razao_social.upper() if venda.cliente else "NÃO INFORMADO"
        plano = venda.plano.nome if venda.plano else "-"
        
        st_tratamento = venda.status_tratamento.nome if venda.status_tratamento else "Sem Tratamento"
        st_esteira = venda.status_esteira.nome if venda.status_esteira else "Não iniciada"
        
        # Detalhe extra se tiver pendência
        extra_info = ""
        if "PENDEN" in st_esteira.upper() and venda.motivo_pendencia:
            extra_info = f"\n⚠️ *Motivo:* {venda.motivo_pendencia.nome}"
        
        if "AGENDADO" in st_esteira.upper() and venda.data_agendamento:
             data_fmt = venda.data_agendamento.strftime('%d/%m/%Y')
             extra_info = f"\n📅 *Data:* {data_fmt} ({venda.get_periodo_agendamento_display()})"

        return (
            f"📋 *STATUS DO PEDIDO*\n\n"
            f"👤 *Cliente:* {cliente_nome}\n"
            f"📦 *Plano:* {plano}\n"
            f"🔢 *O.S:* {venda.ordem_servico or 'S/N'}\n\n"
            f"🔧 *Status Esteira:* {st_esteira}"
            f"{extra_info}\n"
            f"📂 *Status Tratamento:* {st_tratamento}"
        )
    else:
        return (
            f"❌ *PEDIDO NÃO ENCONTRADO*\n\n"
            f"Não localizei nenhuma venda ativa com o {tipo_busca}: *{valor}*.\n"
            f"Verifique a digitação e tente novamente."
        )