def listar_fachadas_dfv_por_endereco(endereco):
    """
    Busca fachadas por endereço (logradouro, bairro ou município) na base DFV.
    """
    if not endereco:
        return ["❌ *Endereço não informado.*"]
    endereco = endereco.strip().upper()
    fachadas = DFV.objects.filter(
        Q(logradouro__icontains=endereco) |
        Q(bairro__icontains=endereco) |
        Q(municipio__icontains=endereco)
    ).filter(
        Q(tipo_viabilidade__icontains='VIAVEL') | Q(tipo_viabilidade__icontains='VIÁVEL')
    ).values_list('num_fachada', 'complemento', 'logradouro', 'bairro', 'tipo_rede', 'nome_cdo', 'cep')
    if not fachadas:
        return [f"❌ *NENHUMA FACHADA ENCONTRADA*\n\nNão encontramos nenhum número viável cadastrado na base DFV para o endereço informado."]
    exemplo = fachadas[0]
    logradouro = exemplo[2] or "Rua Desconhecida"
    bairro = exemplo[3] or "Bairro Desconhecido"
    tecnologia = exemplo[4] or "-"
    nome_cdo = exemplo[5] or "-"
    cep = exemplo[6] or "-"
    def num_compl(num, compl):
        num = (num or '').strip()
        compl = (compl or '').strip()
        if compl:
            return f"{num} ({compl})"
        return num
    numeros = [num_compl(f[0], f[1]) for f in fachadas if f[0]]
    try:
        numeros.sort(key=lambda x: int(''.join(filter(str.isdigit, x.split(' ')[0]))) if any(c.isdigit() for c in x.split(' ')[0]) else 0)
    except:
        numeros.sort()
    total = len(numeros)
    lista_str = ", ".join(numeros)
    cdos = sorted(set([f[5] for f in fachadas if f[5]]))
    cdos_str = ', '.join(cdos) if cdos else '-'
    if len(lista_str) > 3000:
        lista_str = lista_str[:3000] + "... (lista muito longa)"
    mensagem = (
        f"🏢 *RELATÓRIO DE FACHADAS (DFV)*\n\n"
        f"📍 *Endereço:* {logradouro}\n"
        f"🏙️ *Bairro:* {bairro}\n"
        f"🏢 *NOME_CDO(s):* {cdos_str}\n"
        f"📡 *Tecnologia:* {tecnologia}\n"
        f"📬 *CEP:* {cep}\n"
        f"✅ *Total Viáveis:* {total}\n\n"
        f"🔢 *Números Disponíveis (com complemento):*\n"
        f"{lista_str}"
    )
    def split_message(msg, max_len=4096):
        return [msg[i:i+max_len] for i in range(0, len(msg), max_len)]
    return split_message(mensagem)
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
    ).values_list('num_fachada', 'complemento', 'logradouro', 'bairro', 'tipo_rede', 'nome_cdo')

    if not fachadas:
        return (
            f"❌ *NENHUMA FACHADA ENCONTRADA*\n\n"
            f"Não encontramos nenhum número viável cadastrado na base DFV para o CEP {cep_limpo}.\n"
            f"Tente a consulta de *Viabilidade (KMZ)* para ver se a região tem cobertura."
        )

    # Pega dados do logradouro do primeiro resultado para cabeçalho
    exemplo = fachadas[0]
    logradouro = exemplo[2] or "Rua Desconhecida"
    bairro = exemplo[3] or "Bairro Desconhecido"
    tecnologia = exemplo[4] or "-"
    nome_cdo = exemplo[5] or "-"

    # Monta lista de números + complemento
    def num_compl(num, compl):
        num = (num or '').strip()
        compl = (compl or '').strip()
        if compl:
            return f"{num} ({compl})"
        return num

    numeros = [num_compl(f[0], f[1]) for f in fachadas if f[0]]
    try:
        # Ordena pelo número (ignorando complemento)
        numeros.sort(key=lambda x: int(''.join(filter(str.isdigit, x.split(' ')[0]))) if any(c.isdigit() for c in x.split(' ')[0]) else 0)
    except:
        numeros.sort()

    total = len(numeros)
    lista_str = ", ".join(numeros)

    # Listar todos os NOME_CDOs distintos para o CEP
    cdos = sorted(set([f[5] for f in fachadas if f[5]]))
    cdos_str = ', '.join(cdos) if cdos else '-'

    # Se a lista for muito grande, corta para não travar o Zap
    if len(lista_str) > 3000:
        lista_str = lista_str[:3000] + "... (lista muito longa)"

    mensagem = (
        f"🏢 *RELATÓRIO DE FACHADAS (DFV)*\n\n"
        f"📍 *Endereço:* {logradouro}\n"
        f"🏙️ *Bairro:* {bairro}\n"
        f"🏢 *NOME_CDO(s):* {cdos_str}\n"
        f"📡 *Tecnologia:* {tecnologia}\n"
        f"✅ *Total Viáveis:* {total}\n\n"
        f"🔢 *Números Disponíveis (com complemento):*\n"
        f"{lista_str}"
    )

    # Função para dividir mensagem longa em partes de até 4096 caracteres
    def split_message(msg, max_len=4096):
        return [msg[i:i+max_len] for i in range(0, len(msg), max_len)]

    return split_message(mensagem)

def _cep_numero_viavel_no_dfv(cep_limpo, numero):
    """Retorna True se o CEP+número consta na base DFV como viável (fallback quando o mapa não localiza)."""
    if not cep_limpo or not numero:
        return False
    num_str = str(numero).strip()
    # Busca exata (391) ou só o número antes de parênteses (391 (BL 2) -> 391)
    num_limpo = num_str.split("(")[0].strip() if "(" in num_str else num_str
    if not num_limpo.isdigit():
        return False
    existe = DFV.objects.filter(
        cep=cep_limpo,
        num_fachada=num_limpo
    ).filter(
        Q(tipo_viabilidade__icontains='VIAVEL') | Q(tipo_viabilidade__icontains='VIÁVEL')
    ).exists()
    return existe


def consultar_viabilidade_kmz(cep, numero):
    """
    Lógica: CEP+Num -> Lat/Lng -> Verifica Polígono (KMZ).
    Se a geolocalização falhar, consulta a base DFV (fachadas); se o número estiver viável no DFV, retorna viável.
    """
    cep_limpo = limpar_texto(cep)
    print(f"\n🔎 BUSCA KMZ (GEO) -> CEP: {cep_limpo} | NUM: {numero}")

    # 1. Obter Coordenadas
    geo_data = buscar_coordenadas_viacep_nominatim(cep_limpo, numero)

    if not geo_data:
        # Fallback: verificar se CEP+número consta no DFV (base de fachadas viáveis)
        if _cep_numero_viavel_no_dfv(cep_limpo, numero):
            return (
                "✅ *VIABILIDADE TÉCNICA (DFV)*\n\n"
                "O endereço não foi localizado no mapa (KMZ), mas o número consta na base de fachadas como *viável*.\n\n"
                "⚠️ _Sujeito a vistoria técnica local._"
            )
        return "❌ *ENDEREÇO NÃO LOCALIZADO*\nNão conseguimos converter esse CEP e número em coordenadas GPS. Tente enviar a localização (pino) ou use o comando *Fachada* para ver os números viáveis do CEP."

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


def validar_venda_para_resumo_auditoria(venda):
    """
    Valida se a venda está completa para enviar o resumo ao cliente (auditoria).
    Retorna (True, None) se OK, ou (False, mensagem_erro) se faltar algo.
    Exige: endereço (CEP, logradouro, número), plano e forma de pagamento.
    """
    if not venda:
        return False, "Venda não informada."
    if not (venda.cep and str(venda.cep).strip()):
        return False, "Preencha o CEP (aba Endereço) antes de enviar o resumo."
    if not (venda.logradouro and str(venda.logradouro).strip()):
        return False, "Preencha o Logradouro (aba Endereço) antes de enviar o resumo."
    if not (venda.numero_residencia and str(venda.numero_residencia).strip()):
        return False, "Preencha o Número (aba Endereço) antes de enviar o resumo."
    if not venda.plano_id:
        return False, "Selecione o Plano (aba Oferta & Pagamento) antes de enviar o resumo."
    if not venda.forma_pagamento_id:
        return False, "Selecione a Forma de Pagamento (aba Oferta & Pagamento) antes de enviar o resumo."
    return True, None


def montar_resumo_plano_para_whatsapp(venda):
    """
    Monta o texto do resumo da venda (plano, pagamento, endereço completo, cliente) no mesmo
    formato usado no fluxo VENDER, para envio manual (ex.: auditoria enviar ao celular).
    Retorna string pronta para WhatsApp. Use validar_venda_para_resumo_auditoria antes.
    """
    if not venda:
        return ""
    cpf = (venda.cliente.cpf_cnpj or "") if venda.cliente else ""
    cpf_limpo = "".join(filter(str.isdigit, cpf))
    cpf_fmt = f"{cpf_limpo[:3]}.{cpf_limpo[3:6]}.{cpf_limpo[6:9]}-{cpf_limpo[9:]}" if len(cpf_limpo) == 11 else cpf

    celular = (venda.telefone1 or "")
    cel_limpo = "".join(filter(str.isdigit, celular))
    cel_fmt = f"({cel_limpo[:2]}) {cel_limpo[2:7]}-{cel_limpo[7:]}" if len(cel_limpo) >= 10 else celular

    email = (venda.cliente.email or "") if venda.cliente else ""

    # Endereço completo: CEP, logradouro, número, complemento, bairro, cidade, UF, referência
    cep = (venda.cep or "").strip()
    if len(cep) == 8 and cep.isdigit():
        cep = f"{cep[:5]}-{cep[5:]}"
    logradouro = (venda.logradouro or "").strip()
    numero = (venda.numero_residencia or "").strip()
    complemento = (venda.complemento or "").strip()
    bairro = (venda.bairro or "").strip()
    cidade = (venda.cidade or "").strip()
    estado = (venda.estado or "").strip()
    referencia = (venda.ponto_referencia or "").strip()

    linhas_endereco = [f"CEP: {cep}", f"Número: {numero}"]
    if logradouro:
        linhas_endereco.insert(1, f"Logradouro: {logradouro}")
    if complemento:
        linhas_endereco.append(f"Complemento: {complemento}")
    if bairro:
        linhas_endereco.append(f"Bairro: {bairro}")
    if cidade or estado:
        linhas_endereco.append(f"Cidade: {cidade}" + (f" - {estado}" if estado else ""))
    if referencia:
        linhas_endereco.append(f"Referência: {referencia}")
    bloco_endereco = "\n".join(linhas_endereco)

    forma_nome = (venda.forma_pagamento.nome or "") if venda.forma_pagamento else ""
    eh_cartao = forma_nome and ("CRÉDITO" in forma_nome.upper() or "CREDITO" in forma_nome.upper())

    if venda.plano:
        valor_plano = float(venda.plano.valor)
        if eh_cartao:
            valor_plano = max(0, valor_plano - 10)
        plano_linha = f"{venda.plano.nome} - R$ {valor_plano:.2f}/mês".replace(".", ",")
    else:
        plano_linha = "Não informado"

    fixo_linha = "Sim – R$ 30,00/mês" if venda.tem_fixo else "Não"
    streaming_linha = "Não"  # auditoria não possui campo streaming

    return (
        f"📋 *RESUMO DA VENDA*\n\n"
        f"📍 *Endereço:*\n"
        f"{bloco_endereco}\n\n"
        f"👤 *Cliente:*\n"
        f"CPF: {cpf_fmt}\n"
        f"Celular: {cel_fmt}\n"
        f"E-mail: {email}\n\n"
        f"💳 *Pagamento:* {forma_nome}\n"
        f"📦 *Plano:* {plano_linha}\n"
        f"📞 *Fixo:* {fixo_linha}\n"
        f"📺 *Streaming:* {streaming_linha}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Confirma a venda?\n\n"
        f"Digite *CONFIRMAR* para enviar ao PAP\n"
        f"Digite *CANCELAR* para desistir"
    )


def consultar_status_venda_com_decisao(tipo_busca, valor):
    """
    Igual a consultar_status_venda, mas retorna também se deve fazer consulta online no PAP
    e o CPF a usar. Usado pelo fluxo Status no WhatsApp para decidir se dispara Consulta OS.
    Retorna: (resultado_texto, fazer_consulta_online, cpf_para_consulta)
    - fazer_consulta_online: True se (pedido não encontrado) ou (encontrado e (status esteira == AGENDADO ou status esteira não preenchido)) e tiver CPF.
    - cpf_para_consulta: CPF/CNPJ (só dígitos) para a Consulta OS, ou None.
    """
    valor_limpo = limpar_texto(valor)
    venda = None
    cpf_para_consulta = None

    if tipo_busca == 'CPF':
        venda = Venda.objects.filter(
            cliente__cpf_cnpj__icontains=valor_limpo,
            ativo=True
        ).order_by('-data_criacao').select_related('cliente', 'status_esteira', 'status_tratamento', 'plano').first()
        cpf_para_consulta = valor_limpo if len(valor_limpo) in (11, 14) else None
    elif tipo_busca == 'OS':
        venda = Venda.objects.filter(
            ordem_servico=valor_limpo,
            ativo=True
        ).select_related('cliente', 'status_esteira', 'status_tratamento', 'plano').first()
        if venda and venda.cliente and venda.cliente.cpf_cnpj:
            cpf_para_consulta = limpar_texto(venda.cliente.cpf_cnpj)
            if len(cpf_para_consulta) not in (11, 14):
                cpf_para_consulta = None

    texto = consultar_status_venda(tipo_busca, valor)

    if not venda:
        # Pedido não encontrado: consulta online só se tivermos CPF (fluxo por CPF)
        fazer_online = bool(cpf_para_consulta)
        return (texto, fazer_online, cpf_para_consulta)
    st_esteira = ((venda.status_esteira.nome if venda.status_esteira else None) or "").strip().upper()
    # Liberar consulta online quando: AGENDADO ou quando status_esteira não estiver preenchido
    fazer_online = bool(cpf_para_consulta) and (st_esteira == "AGENDADO" or not st_esteira)
    if fazer_online:
        return (texto, True, cpf_para_consulta)
    return (texto, False, None)


def consultar_previsao_agendamento(numero_pedido):
    """
    Busca a previsão de instalação na base de agendamentos futuros e tarefas fechadas.
    Retorna a data/hora de início e fim da execução real.
    """
    from .models import ImportacaoAgendamento
    from django.db.models import Q
    
    numero_limpo = str(numero_pedido).strip()
    numero_sem_zero = numero_limpo.lstrip("0") or numero_limpo
    print(f"\n📅 BUSCA PREVISÃO -> Pedido: {numero_limpo} | sem zero: {numero_sem_zero}")
    
    # Busca combinando ordem e ordem de venda, considerando zeros à esquerda
    filtros = Q(nr_ordem__icontains=numero_limpo) | Q(nr_ordem_venda__icontains=numero_limpo)
    if numero_sem_zero != numero_limpo:
        filtros |= Q(nr_ordem__icontains=numero_sem_zero) | Q(nr_ordem_venda__icontains=numero_sem_zero)
        filtros |= Q(nr_ordem__iexact=numero_sem_zero) | Q(nr_ordem_venda__iexact=numero_sem_zero)
    filtros |= Q(nr_ordem__iexact=numero_limpo) | Q(nr_ordem_venda__iexact=numero_limpo)

    agendamento = ImportacaoAgendamento.objects.filter(filtros).first()
    
    if agendamento:
        # Formata as datas
        dt_inicio = agendamento.dt_inicio_execucao_real
        dt_fim = agendamento.dt_fim_execucao_real
        
        # Informações do agendamento
        municipio = agendamento.nm_municipio or "Não informado"
        uf = agendamento.sg_uf or ""
        status_ba = agendamento.st_ba or "Em andamento"
        atividade = agendamento.ds_atividade or "Instalação"
        
        # Monta a mensagem
        if dt_inicio and dt_fim:
            # Formata as datas
            inicio_fmt = dt_inicio.strftime('%d/%m/%Y às %H:%M')
            fim_fmt = dt_fim.strftime('%d/%m/%Y às %H:%M')
            
            return (
                f"📅 *PREVISÃO DE INSTALAÇÃO*\n\n"
                f"🔢 *Pedido:* {numero_limpo}\n"
                f"📍 *Local:* {municipio}/{uf}\n"
                f"🔧 *Atividade:* {atividade}\n"
                f"📊 *Status:* {status_ba}\n\n"
                f"⏰ *Previsão de Início:*\n{inicio_fmt}\n\n"
                f"⏰ *Previsão de Término:*\n{fim_fmt}"
            )
        elif agendamento.dt_agendamento:
            # Só tem data de agendamento
            agend_fmt = agendamento.dt_agendamento.strftime('%d/%m/%Y')
            return (
                f"📅 *PREVISÃO DE INSTALAÇÃO*\n\n"
                f"🔢 *Pedido:* {numero_limpo}\n"
                f"📍 *Local:* {municipio}/{uf}\n"
                f"🔧 *Atividade:* {atividade}\n"
                f"📊 *Status:* {status_ba}\n\n"
                f"⏰ *Data Agendada:* {agend_fmt}\n"
                f"⚠️ *Horário de execução ainda não disponível*"
            )
        else:
            return (
                f"📅 *PREVISÃO DE INSTALAÇÃO*\n\n"
                f"🔢 *Pedido:* {numero_limpo}\n"
                f"📍 *Local:* {municipio}/{uf}\n"
                f"📊 *Status:* {status_ba}\n\n"
                f"⚠️ *Datas de execução ainda não disponíveis*\n"
                f"O agendamento está registrado mas ainda sem previsão de horário."
            )
    else:
        return (
            f"❌ *PEDIDO NÃO ENCONTRADO*\n\n"
            f"Não localizei o pedido *{numero_limpo}* na base de agendamentos.\n\n"
            f"Verifique:\n"
            f"• Se o número está correto\n"
            f"• Se o pedido já foi agendado\n"
            f"• Se foi importado na última base"
        )


def consultar_andamento_agendamentos(telefone_vendedor=None):
    """
    Busca agendamentos do dia atual com horários de execução real definidos.
    Se telefone_vendedor for fornecido, filtra apenas agendamentos do vendedor.
    Para Diretoria, Admin e BackOffice, mostra todos os agendamentos.
    Retorna mensagem formatada com os clientes e intervalos de horário.
    """
    from .models import ImportacaoAgendamento, Venda
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from django.db.models import Q
    
    # Importar is_member (definida em outro arquivo, geralmente em views.py ou utils.py)
    try:
        from crm_app.views import is_member
    except ImportError:
        # Fallback: função simples para verificar grupos
        def is_member(user, grupos):
            if not user or not user.groups.exists():
                return False
            grupos_user = [g.name for g in user.groups.all()]
            return any(grupo in grupos_user for grupo in grupos)
    
    User = get_user_model()
    hoje = timezone.now().date()
    
    # Se telefone fornecido, buscar vendedor
    vendedor = None
    mostrar_todos = False
    if telefone_vendedor:
        # Limpar telefone (remover caracteres não numéricos)
        telefone_limpo = "".join(filter(str.isdigit, str(telefone_vendedor)))
        # Tentar buscar com e sem código 55
        if telefone_limpo.startswith('55'):
            telefone_limpo_sem_55 = telefone_limpo[2:]
        else:
            telefone_limpo_sem_55 = telefone_limpo
        
        vendedor = User.objects.filter(
            Q(tel_whatsapp__icontains=telefone_limpo) |
            Q(tel_whatsapp__icontains=telefone_limpo_sem_55) |
            Q(tel_whatsapp_2__icontains=telefone_limpo) |
            Q(tel_whatsapp_2__icontains=telefone_limpo_sem_55) |
            Q(tel_whatsapp_3__icontains=telefone_limpo) |
            Q(tel_whatsapp_3__icontains=telefone_limpo_sem_55)
        ).first()
        
        if not vendedor:
            return (
                "📅 *AGENDAMENTOS DO DIA*\n\n"
                f"❌ Vendedor não encontrado para o número {telefone_vendedor}.\n"
                "Verifique se o número está cadastrado no sistema."
            )
        
        # Verificar se é Diretoria, Admin ou BackOffice
        grupos_gestao = ['Diretoria', 'Admin', 'BackOffice']
        mostrar_todos = is_member(vendedor, grupos_gestao)
    
    # Buscar agendamentos do dia com horários de execução real preenchidos
    agendamentos_qs = ImportacaoAgendamento.objects.filter(
        dt_agendamento=hoje,
        dt_inicio_execucao_real__isnull=False,
        dt_fim_execucao_real__isnull=False
    )
    
    # Se vendedor especificado e NÃO for gestão, filtrar apenas suas vendas
    if vendedor and not mostrar_todos:
        # Buscar ordens_servico das vendas desse vendedor
        vendas_vendedor = Venda.objects.filter(
            vendedor=vendedor,
            ativo=True,
            ordem_servico__isnull=False
        ).exclude(ordem_servico='').values_list('ordem_servico', flat=True)
        
        ordens_list = list(vendas_vendedor)
        
        if not ordens_list:
            return (
                "📅 *AGENDAMENTOS DO DIA*\n\n"
                f"❌ Não há agendamentos para hoje ({hoje.strftime('%d/%m/%Y')}) "
                f"relacionados às suas vendas."
            )
        
        # Filtrar agendamentos cujo nr_ordem_venda está nas ordens do vendedor
        agendamentos_qs = agendamentos_qs.filter(
            Q(nr_ordem_venda__in=ordens_list) | Q(nr_ordem__in=ordens_list)
        )
    
    agendamentos = agendamentos_qs.order_by('dt_inicio_execucao_real')
    
    if not agendamentos.exists():
        msg_base = f"📅 *AGENDAMENTOS DO DIA*\n\n"
        if vendedor:
            msg_base += f"Vendedor: {vendedor.username}\n\n"
        msg_base += f"❌ Não há agendamentos para hoje ({hoje.strftime('%d/%m/%Y')}) com horários de execução definidos."
        return msg_base
    
    mensagens = []
    mensagens.append(f"📅 *AGENDAMENTOS DO DIA*\n\nData: {hoje.strftime('%d/%m/%Y')}\n")
    if vendedor:
        mensagens.append(f"Vendedor: *{vendedor.username}*\n")
    mensagens.append(f"Total: {agendamentos.count()} agendamento(s)\n")
    mensagens.append("=" * 30 + "\n")
    
    for idx, agend in enumerate(agendamentos, 1):
        # Tentar encontrar a venda relacionada
        cliente_nome = "Cliente não identificado"
        os_num = agend.nr_ordem_venda or agend.nr_ordem or "N/A"
        
        if agend.nr_ordem_venda:
            # Buscar venda por ordem_servico
            venda = Venda.objects.filter(
                ordem_servico=agend.nr_ordem_venda,
                ativo=True
            ).select_related('cliente').first()
            
            if venda and venda.cliente:
                cliente_nome = venda.cliente.nome_razao_social or cliente_nome
        
        # Formatar horários
        inicio_fmt = agend.dt_inicio_execucao_real.strftime('%H:%M')
        fim_fmt = agend.dt_fim_execucao_real.strftime('%H:%M')
        intervalo = f"{inicio_fmt} - {fim_fmt}"
        
        # Informações adicionais
        municipio = agend.nm_municipio or ""
        atividade = agend.ds_atividade or "Instalação"
        
        mensagens.append(f"{idx}. *{cliente_nome}*\n")
        mensagens.append(f"   🔢 O.S: {os_num}\n")
        mensagens.append(f"   ⏰ Horário: {intervalo}\n")
        if municipio:
            mensagens.append(f"   📍 Local: {municipio}\n")
        if atividade:
            mensagens.append(f"   🔧 Atividade: {atividade}\n")
        mensagens.append("\n")
    
    return "".join(mensagens).strip()