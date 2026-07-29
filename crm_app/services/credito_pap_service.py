"""Seleção de endereço e contatos usados na análise de crédito do PAP.

Regras de negócio isoladas aqui:

* Endereço: usa o endereço cadastral da Assertiva e, quando o PAP responde sem
  viabilidade (ou com pedido/posse no endereço), refaz a consulta com o endereço
  padrão da automação para não abortar a análise.
* Contatos: usa telefone/e-mail reais da Assertiva; quando o PAP recusa todos
  (contato já utilizado em pedido anterior), volta ao celular aleatório e ao
  e-mail validado do pool, que o portal aceita receber.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from crm_app.credito_utils import gerar_celular_random, gerar_email_credito
from crm_app.services.assertiva_localize_service import EnderecoAssertiva

logger = logging.getLogger(__name__)

ORIGEM_ASSERTIVA = "assertiva"
ORIGEM_PADRAO = "padrao"
ORIGEM_ALEATORIO = "aleatorio"
ORIGEM_MISTO = "misto"

# Códigos da etapa 2 que indicam bloqueio do endereço (e não do cliente),
# portanto passíveis de nova tentativa com outro endereço.
CODIGOS_ENDERECO_BLOQUEADO = ("INDISPONIVEL_TECNICO", "POSSE_ENCONTRADA")


@dataclass(frozen=True)
class EnderecoCredito:
    """Endereço candidato para a consulta de viabilidade."""

    cep: str
    numero: str
    referencia: str
    logradouro: str = ""
    origem: str = ORIGEM_ASSERTIVA

    def como_dict(self) -> dict[str, str]:
        return {
            "cep": self.cep,
            "numero": self.numero,
            "referencia": self.referencia,
            "logradouro": self.logradouro,
            "origem": self.origem,
        }


@dataclass(frozen=True)
class ContatoCredito:
    """Telefone e e-mail que serão enviados na etapa de contato."""

    telefone: str
    email: str
    telefone_secundario: Optional[str] = None
    origem_telefone: str = ORIGEM_ASSERTIVA
    origem_email: str = ORIGEM_ASSERTIVA


@dataclass
class ResultadoViabilidade:
    """Resultado consolidado da etapa 2 após as tentativas de endereço."""

    sucesso: bool
    mensagem: str
    endereco: Optional[EnderecoCredito] = None
    bloqueios: list[str] = field(default_factory=list)

    @property
    def usou_fallback(self) -> bool:
        return bool(self.endereco and self.endereco.origem != ORIGEM_ASSERTIVA)


def montar_tentativas_endereco(
    endereco_assertiva: Optional[EnderecoAssertiva],
    *,
    endereco_padrao: EnderecoCredito,
) -> tuple[EnderecoCredito, ...]:
    """Ordena os endereços: o real do cliente primeiro, o padrão como reserva."""
    if endereco_assertiva is None:
        return (endereco_padrao,)

    candidato = EnderecoCredito(
        cep=endereco_assertiva.cep,
        numero=endereco_assertiva.numero,
        referencia=endereco_assertiva.referencia,
        logradouro=endereco_assertiva.logradouro,
        origem=ORIGEM_ASSERTIVA,
    )
    mesmo_endereco = (
        candidato.cep == endereco_padrao.cep
        and candidato.numero == endereco_padrao.numero
    )
    if mesmo_endereco:
        return (candidato,)
    return (candidato, endereco_padrao)


def _executar_etapa2(
    automacao: Any,
    endereco: EnderecoCredito,
) -> tuple[bool, str, Any]:
    """Roda a etapa 2 tratando complementos e múltiplos endereços do PAP."""
    sucesso, mensagem, extra = automacao.etapa2_viabilidade(
        endereco.cep,
        endereco.numero,
        endereco.referencia,
    )
    if isinstance(extra, dict) and extra.get("_codigo") == "COMPLEMENTOS":
        sucesso, mensagem, extra = (
            automacao.etapa2_credito_selecionar_complemento_e_avancar(
                endereco.cep,
                endereco.numero,
                1,
            )
        )
    if (
        not sucesso
        and isinstance(extra, dict)
        and extra.get("_codigo") == "MULTIPLOS_ENDERECOS"
    ):
        indice = _indice_endereco_desejado(extra.get("lista") or [], endereco)
        ok_selecao, _ = automacao.etapa2_selecionar_endereco_instalacao(indice)
        if ok_selecao:
            sucesso, mensagem, extra = (
                automacao.etapa2_preencher_referencia_e_continuar(
                    endereco.cep,
                    endereco.numero,
                    endereco.referencia,
                )
            )
            if isinstance(extra, dict) and extra.get("_codigo") == "COMPLEMENTOS":
                sucesso, mensagem, extra = (
                    automacao.etapa2_credito_selecionar_complemento_e_avancar(
                        endereco.cep,
                        endereco.numero,
                        1,
                    )
                )
    return sucesso, mensagem, extra


def _indice_endereco_desejado(
    lista: Sequence[dict[str, Any]],
    endereco: EnderecoCredito,
) -> int:
    alvo = (endereco.logradouro or "").upper()
    for item in lista:
        texto = str(item.get("texto") or "").upper()
        if alvo and alvo in texto and endereco.numero in texto:
            return int(item.get("indice", 1))
    return 1


def _resumo_bloqueio(
    endereco: EnderecoCredito,
    codigo: Optional[str],
    mensagem: str,
) -> str:
    if codigo:
        detalhe = codigo
    else:
        primeira_linha = (mensagem or "").strip().splitlines()
        detalhe = primeira_linha[0] if primeira_linha else "falha não classificada"
    return f"{endereco.origem}:{endereco.cep}/{endereco.numero} - {detalhe}"


def consultar_viabilidade_com_fallback(
    automacao: Any,
    tentativas: Sequence[EnderecoCredito],
) -> ResultadoViabilidade:
    """
    Consulta a viabilidade percorrendo os endereços candidatos.

    Só reconsulta quando o PAP bloqueou o endereço (sem viabilidade / posse);
    falhas de página ou do portal encerram a etapa para não mascarar erro real.
    """
    resultado = ResultadoViabilidade(
        sucesso=False,
        mensagem="Nenhum endereço disponível para consulta.",
    )
    total = len(tentativas)
    for indice, endereco in enumerate(tentativas):
        sucesso, mensagem, extra = _executar_etapa2(automacao, endereco)
        if sucesso:
            resultado.sucesso = True
            resultado.mensagem = mensagem
            resultado.endereco = endereco
            return resultado

        codigo = extra if isinstance(extra, str) else None
        resultado.mensagem = mensagem
        resultado.endereco = endereco
        resultado.bloqueios.append(_resumo_bloqueio(endereco, codigo, mensagem))

        ultima_tentativa = indice >= total - 1
        if codigo not in CODIGOS_ENDERECO_BLOQUEADO or ultima_tentativa:
            return resultado

        ok_reset, msg_reset = automacao.etapa2_preparar_nova_consulta_endereco(codigo)
        if not ok_reset:
            logger.warning(
                "[CRÉDITO] Não foi possível voltar ao formulário de CEP: %s",
                msg_reset,
            )
            return resultado
        logger.warning(
            "[CRÉDITO] Endereço %s (%s/%s) bloqueado no PAP (%s) — tentando endereço padrão da automação.",
            endereco.origem,
            endereco.cep,
            endereco.numero,
            codigo,
        )
    return resultado


class SeletorContatosCredito:
    """
    Entrega os contatos da etapa 4 e avança quando o PAP recusa algum.

    Esgotados os dados da Assertiva, passa a sortear celular e a usar o e-mail
    validado (`gerar_email_credito`), evitando encerrar a análise por recusa de
    contato repetido.
    """

    def __init__(
        self,
        telefones: Sequence[str] = (),
        emails: Sequence[str] = (),
    ) -> None:
        self._telefones = [str(t).strip() for t in telefones if str(t).strip()]
        self._emails = [str(e).strip() for e in emails if str(e).strip()]
        self._indice_telefone = 0
        self._indice_email = 0
        self._telefone_aleatorio: Optional[str] = None
        self._telefone_secundario_aleatorio: Optional[str] = None
        self._email_aleatorio: Optional[str] = None
        self._usou_telefone_aleatorio = False
        self._usou_email_aleatorio = False

    def atual(self) -> ContatoCredito:
        telefone, secundario, origem_telefone = self._telefone_atual()
        email, origem_email = self._email_atual()
        return ContatoCredito(
            telefone=telefone,
            email=email,
            telefone_secundario=secundario,
            origem_telefone=origem_telefone,
            origem_email=origem_email,
        )

    def proximo_telefone(self) -> ContatoCredito:
        """Avança para o próximo telefone da Assertiva ou sorteia um novo."""
        if self._tem_telefone_assertiva():
            self._indice_telefone += 1
        if not self._tem_telefone_assertiva():
            self._sortear_telefone()
        return self.atual()

    def proximo_email(self) -> ContatoCredito:
        """Avança para o próximo e-mail da Assertiva ou usa o pool validado."""
        if self._tem_email_assertiva():
            self._indice_email += 1
        if not self._tem_email_assertiva():
            self._sortear_email()
        return self.atual()

    @property
    def origem_contato(self) -> str:
        if self._usou_telefone_aleatorio and self._usou_email_aleatorio:
            return ORIGEM_ALEATORIO
        if self._usou_telefone_aleatorio or self._usou_email_aleatorio:
            return ORIGEM_MISTO
        return ORIGEM_ASSERTIVA

    def _tem_telefone_assertiva(self) -> bool:
        return self._indice_telefone < len(self._telefones)

    def _tem_email_assertiva(self) -> bool:
        return self._indice_email < len(self._emails)

    def _telefone_atual(self) -> tuple[str, Optional[str], str]:
        if self._tem_telefone_assertiva():
            telefone = self._telefones[self._indice_telefone]
            proximo = self._indice_telefone + 1
            secundario = (
                self._telefones[proximo] if proximo < len(self._telefones) else None
            )
            return telefone, secundario, ORIGEM_ASSERTIVA
        if not self._telefone_aleatorio:
            self._sortear_telefone()
        return (
            str(self._telefone_aleatorio),
            self._telefone_secundario_aleatorio,
            ORIGEM_ALEATORIO,
        )

    def _email_atual(self) -> tuple[str, str]:
        if self._tem_email_assertiva():
            return self._emails[self._indice_email], ORIGEM_ASSERTIVA
        if not self._email_aleatorio:
            self._sortear_email()
        return str(self._email_aleatorio), ORIGEM_ALEATORIO

    def _sortear_telefone(self) -> None:
        self._telefone_aleatorio = gerar_celular_random()
        self._telefone_secundario_aleatorio = gerar_celular_random()
        self._usou_telefone_aleatorio = True

    def _sortear_email(self) -> None:
        self._email_aleatorio = gerar_email_credito()
        self._usou_email_aleatorio = True
