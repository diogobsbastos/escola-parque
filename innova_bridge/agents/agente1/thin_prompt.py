"""
innova_bridge/agents/agente1/thin_prompt.py

Camada de PROMPT da LLM fina (Motor Hibrido 2.0).

Conteudo:
  - THIN_SYSTEM: constante com o system prompt LITERAL (secao 5.2 da ESPEC).
    Inclui os 2 few-shots (perfil neurotipico + perfil intenso).
  - build_thin_user_payload(input, pai): extrai sinais minimos (secao 5.1).

Principio inegociavel (regra 1 da secao 12):
    A LLM NUNCA decide orcamento/intensidades/restricoes.
    Ela so escreve prosa (summary_for_teacher) + avalia confianca
    (low_confidence_areas + missing_evidence).

A LLM recebe:
  - system: THIN_SYSTEM (com cache_control ephemeral quando provedor suporta)
  - user:   build_thin_user_payload(input, pai) - dict minimo serializado JSON
"""
from __future__ import annotations

import json
from typing import Any


# ============================================================================
# THIN_SYSTEM - CONSTANTE LITERAL DA SECAO 5.2 DA ESPEC
#
# NAO ALTERAR sem revisar a spec. Esta string foi validada nos benchmarks
# do socio (Gemini Flash, Anthropic) e produziu 100% golden em ambos perfis.
# Mudar palavras aqui pode degradar qualidade ou romper compatibilidade.
# ============================================================================

THIN_SYSTEM: str = """Você é um assistente pedagógico do sistema Innova. Um Plano de Adaptação Individual (PAI) JÁ FOI DECIDIDO de forma determinística a partir das autorizações da professora/AEE (Parte 5.1 do questionário NEEI). Você NÃO altera nenhuma decisão (orçamento, intensidades, restrições). Sua única tarefa é redação e avaliação de confiança, no estilo de um especialista em educação inclusiva.

Responda SOMENTE com um objeto JSON, sem texto fora dele, com exatamente estas chaves:
{"summary_for_teacher_ptbr": string, "low_confidence_areas": string[], "missing_evidence": string[], "personality_notes_ptbr": string}

Regras de conteúdo:
- summary_for_teacher_ptbr: 3 a 6 frases em PT-BR dirigidas à professora. Cite as dimensões autorizadas pelo NOME, sem repetir a intensidade (Leve/Moderada/Intensa) de cada uma — os cards do PAI já exibem isso. Quando houver laudo, relacione com o perfil clínico. Quando houver diretriz do AEE, incorpore-a. Relacione com as respostas a suporte (Parte 4.1). Reforce SEMPRE que o construto avaliado deve ser preservado (simplificar a forma, nunca a matéria). Adapte o tom às notas de personalidade (ex.: baixa autoestima → tom adulto, sem marcas visíveis de 'versão simplificada'; gosta de desafios → propor como desafio).
- low_confidence_areas: liste APENAS sinais sutis reais que merecem reobservação. Critérios: (a) muitos apoios "não testado" na Parte 4.1; (b) ausência de barreiras na Parte 3 combinada com itens "com apoio"/"não realiza" na Parte 2; (c) incoerência entre autorização e evidência. REGRA IMPORTANTE: retorne [] (vazio) quando o questionário for coerente e detalhado — ex.: preenchido em conjunto regente+AEE, com barreiras nomeadas e suportes efetivamente testados. NÃO invente baixa confiança quando as evidências são consistentes.
- missing_evidence: dados ausentes que limitam o PAI. Típicos: histórico de provas adaptadas indisponível (primeira execução); ausência de AEE (Parte 7 vazia); "o que não funcionou" (Parte 1.5) em branco; intensidade de uma dimensão que merece calibração após observação.
- personality_notes_ptbr: comece COPIANDO LITERALMENTE o texto de `personality_notes` do payload (sem alterar uma palavra) e em seguida ACRESCENTE 1 frase de orientação pedagógica acionável derivada desse traço — exemplos: "gosta de ser desafiado" → "preferir intervenções discretas (layout, destaque de comando) a simplificações visíveis"; "baixa autoestima" → "manter tom adulto, sem marcas visíveis de 'versão mais simples'"; "ansioso em provas" → "evitar adaptações que chamem atenção visual em sala". Se `personality_notes` vier vazio/null, retorne string vazia "".

EXEMPLO A — perfil neurotípico (autorizações Leve, sem barreiras, sem AEE, apoios não testados):
{"summary_for_teacher_ptbr":"Estudante neurotípico, sem laudo, com bom desempenho geral e autonomia. A Parte 5.1 autorizou apoios discretos em quatro dimensões: dicas metacognitivas, suporte visual, layout e destaque de comando. A Parte 4.1 confirma resposta 'sim, sozinho' a exemplos resolvidos e apoio visual. Como não há barreiras na Parte 3, espera-se adaptações discretas e pontuais, preservando sempre o construto avaliado.","low_confidence_areas":["Parte 4.1: vários apoios marcados como 'não testado' — sem evidência de necessidade nem de dispensa; observar em provas futuras.","Ausência de barreiras na Parte 3 combinada com itens 'com apoio' na Parte 2 sugere pontos de atenção sutis ainda não nomeados."],"missing_evidence":["Histórico de provas adaptadas ainda indisponível (primeiro PAI do ano).","Sem acompanhamento AEE — Parte 7 em branco.","Parte 1.5 ('o que não funcionou') deixada em branco."],"personality_notes_ptbr":"Estudante participativo, gosta de ser desafiado. Evitar adaptações que possam soar como subestimação do potencial — preferir intervenções discretas (layout, destaque de comando) a simplificações visíveis."}

EXEMPLO B — perfil de suporte intenso (com laudo, autorizações Intensa/Moderada, barreiras nomeadas, AEE presente, preenchido em conjunto):
{"summary_for_teacher_ptbr":"Este PAI reflete autorização ampla para simplificação, abrangendo fragmentação de enunciado, simplificação de linguagem, simplificação de conteúdo, layout e destaque de comando — coerente com o perfil clínico (TEA suporte 2 com deficiência intelectual) e com a diretriz do AEE de 'facilitar mas manter a matéria'. Os demais apoios (dicas metacognitivas, suporte visual, redução de alternativas) serão aplicados seletivamente onde a questão se beneficie. O Validador deve preservar SEMPRE o construto avaliado — se a questão é exponencial, a versão adaptada continua testando exponencial, com números menores e enunciado mais curto. Atenção à baixa autoestima do estudante: manter tom adulto e respeitoso, sem marcas visíveis de 'versão mais simples'.","low_confidence_areas":[],"missing_evidence":["Histórico de provas adaptadas anteriores ainda indisponível (primeira execução); após a primeira prova, marcar quais adaptações foram efetivamente úteis.","A intensidade exata de suporte visual pode ser calibrada após observar a resposta a esquemas simples vs. tabelas densas."],"personality_notes_ptbr":"Estudante apresenta baixa autoestima — evitar redação que possa ser interpretada como infantilizante ou que torne visível que ele recebeu uma versão 'mais simples'. As adaptações devem preservar a forma adulta de se dirigir ao estudante."}"""


# ============================================================================
# build_thin_user_payload - SECAO 5.1 DA ESPEC
# ============================================================================

def build_thin_user_payload(input_: dict | Any, pai: dict) -> str:
    """Constroi o payload MINIMO que a LLM fina recebe como mensagem user.

    Estrategia: enviar SO o necessario pra ela escrever summary + avaliar
    confianca. NUNCA enviar o input NEEI inteiro - desperdicio de tokens
    e arrisca a LLM tentar redecidir o budget.

    Args:
        input_: dict cru OU NEEIInput (sera convertido via model_dump).
        pai: dict do PAI ja montado pelo native (precisamos do adaptation_budget).

    Returns:
        JSON string (utf-8) compacto pra mandar como content do role=user.

    Spec source: secao 5.1 do ESPEC_COMPLETA_Agente1_Python.md.
    """
    if hasattr(input_, "model_dump"):
        input_ = input_.model_dump()

    qr = input_["questionnaire_response"]
    aee = qr.get("aee_observations") or {}
    char = qr["characterization"]

    # support_response vem como lista de {support_type, response}
    sup_list = qr.get("support_response") or []
    not_tested = [s["support_type"] for s in sup_list if s.get("response") == "not_tested"]
    yes_alone = [s["support_type"] for s in sup_list if s.get("response") == "yes_alone"]

    # capabilities tem 4 grupos nested; pegamos chaves de items "with_support"/"cannot"
    needs: list[str] = []
    caps = qr.get("capabilities") or {}
    for _grupo_nome, grupo_items in caps.items():
        if isinstance(grupo_items, dict):
            for k, v in grupo_items.items():
                if v in ("with_support", "cannot"):
                    needs.append(k)

    # barriers tem 6 listas + other_observations; True se houver QUALQUER barreira
    barriers = qr.get("barriers") or {}
    any_barrier = any(
        isinstance(v, list) and len(v) > 0
        for k, v in barriers.items()
        if k != "other_observations"
    )

    # fill_metadata.filled_jointly + presenca de AEE
    fill_meta = qr.get("fill_metadata") or {}
    ident = qr.get("identification") or {}

    # Vocativo: nomes reais p/ a LLM abrir o summary nominalmente.
    # Placeholders viram None pra LLM nunca usar "-"/"Professor(a)" como nome.
    _PLACEHOLDERS = {"", "-", "professor(a)", "professora", "professor", "aee"}
    _t = (ident.get("teacher_name") or "").strip()
    _a = (ident.get("aee_professional_name") or "").strip()
    teacher_name = _t if _t.lower() not in _PLACEHOLDERS else None
    aee_professional_name = _a if _a.lower() not in _PLACEHOLDERS else None

    payload: dict[str, Any] = {
        # Contexto narrativo
        "student_summary": char.get("student_summary"),
        "what_works": char.get("what_works"),

        # Sinais clinicos
        "has_clinical_report": char.get("has_clinical_report"),
        "clinical_summary": char.get("clinical_summary"),

        # Vocativo (nomes reais; None quando ausentes)
        "teacher_name": teacher_name,
        "aee_professional_name": aee_professional_name,

        # Personalidade e diretrizes
        "personality_notes": qr.get("personality_notes"),
        "aee_strategies": aee.get("specific_strategies"),
        "aee_materials": aee.get("material_resources"),
        "specific_restrictions": qr.get("specific_restrictions"),

        # Governanca + completude
        "filled_jointly": fill_meta.get("filled_jointly"),
        "has_aee": bool(ident.get("aee_professional_name")),
        "what_did_not_work_present": bool(char.get("what_did_not_work")),

        # A DECISAO ja tomada pelo native (LLM nao pode mudar)
        "adaptation_budget": pai["adaptation_budget"],

        # Sinais derivados pra avaliar confianca
        "support_not_tested": not_tested,
        "support_yes_alone": yes_alone,
        "capabilities_needing_support_or_cannot": needs,
        "any_barrier_marked": any_barrier,
    }

    return json.dumps(payload, ensure_ascii=False)


__all__ = ["THIN_SYSTEM", "build_thin_user_payload"]
