#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
unidate — espelha compromissos entre as agendas do Calendário do macOS
como blocos "Ocupado", sem copiar título, participantes, local ou notas.

Uso:
    unidate.py calendars            lista todas as agendas visíveis
    unidate.py init [--force]       cria/recria o arquivo de configuração
    unidate.py sync [--dry-run]     executa a sincronização
    unidate.py status               mostra estatísticas dos espelhos
    unidate.py purge [--yes]        remove TODOS os espelhos criados por este script

Segurança: o script só remove ou altera eventos que ele próprio criou,
identificados pela assinatura "[unidate/v1] src=..." no campo de notas.
Nenhum evento seu é modificado em momento algum.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

# --------------------------------------------------------------------------
# Dependências nativas (PyObjC)
# --------------------------------------------------------------------------
try:
    from Foundation import NSDate, NSRunLoop, NSDefaultRunLoopMode
    import EventKit
except ImportError:
    sys.stderr.write(
        "ERRO: PyObjC/EventKit não encontrado.\n"
        "Instale com:\n"
        "  /usr/bin/python3 -m pip install --target ~/.unidate/lib "
        "pyobjc-framework-EventKit\n"
        "e garanta que PYTHONPATH aponte para essa pasta.\n"
    )
    sys.exit(2)


def _ek(name, default):
    return getattr(EventKit, name, default)


EK_ENTITY_EVENT = _ek("EKEntityTypeEvent", 0)
EK_SPAN_THIS = _ek("EKSpanThisEvent", 0)
EK_AVAIL_BUSY = _ek("EKEventAvailabilityBusy", 0)
EK_AVAIL_FREE = _ek("EKEventAvailabilityFree", 1)
EK_STATUS_CANCELED = _ek("EKEventStatusCanceled", 3)
EK_PART_DECLINED = _ek("EKParticipantStatusDeclined", 3)
EK_CAL_SUBSCRIPTION = _ek("EKCalendarTypeSubscription", 3)
EK_CAL_BIRTHDAY = _ek("EKCalendarTypeBirthday", 4)
EK_SRC_LOCAL = _ek("EKSourceTypeLocal", 0)

# O Exchange expõe a agenda de aniversários como agenda comum (tipo Exchange),
# não como EKCalendarTypeBirthday — só o nome a distingue.
NOMES_ANIVERSARIOS = ("aniversários", "aniversarios", "birthdays", "geburtstage",
                      "cumpleaños", "anniversaires", "compleanni")

CAL_TYPE_NAMES = {0: "Local", 1: "CalDAV/iCloud", 2: "Exchange", 3: "Assinatura", 4: "Aniversários"}

# --------------------------------------------------------------------------
# Constantes do pacote
# --------------------------------------------------------------------------
BASE_DIR = os.path.expanduser("~/.unidate")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
LOCK_PATH = os.path.join(BASE_DIR, "unidate.lock")

MARKER_PREFIX = "[unidate/v1] src="
# Escreve sempre [unidate/v1], mas continua lendo [calsync/v1]: blocos criados
# antes do rename que estão fora da janela de sincronização nunca serão
# re-estampados, e sem isto ficariam invisíveis até para o purge.
MARKER_RE = re.compile(r"\[(?:unidate|calsync)/v1\]\s*src=([0-9a-f]{16})")

NOTE_TEMPLATE = (
    "Bloco automático de indisponibilidade.\n"
    "Criado e mantido por unidate — não edite nem apague manualmente.\n"
    + MARKER_PREFIX
    + "{key}"
)

DEFAULT_CONFIG = {
    "titulo_espelho": "Ocupado",
    "dias_a_frente": 60,
    "dias_atras": 1,
    "incluir_dia_inteiro": False,
    "ignorar_eventos_livres": True,
    "ignorar_recusados": True,
    "ignorar_cancelados": True,
    "duracao_minima_min": 0,
    "duracao_maxima_horas": 24,
    # piso da duração do bloco: um convite de 15 min vira um "Ocupado" de 30 min
    "duracao_minima_bloco_min": 30,
    # cobertura_total  -> só pula se a agenda de destino já estiver ocupada
    #                     durante TODO o intervalo do compromisso
    # qualquer_sobreposicao -> pula se houver qualquer sobreposição
    # nunca -> sempre cria o espelho
    # Teto de escritas por ciclo. Uma rajada (conta readicionada, horizonte
    # ampliado) faz Google/Exchange rejeitarem em massa e a conta acender erro
    # de sincronização. O sync é idempotente: o excedente sai no ciclo seguinte.
    "max_mudancas_por_ciclo": 100,
    # minutos entre ciclos automáticos (o app relê isto a cada ciclo)
    "intervalo_minutos": 15,
    "politica_sobreposicao": "cobertura_total",
    "agendas": [],
}


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def log(msg: str) -> None:
    print("[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def to_nsdate(dt: datetime) -> "NSDate":
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def from_nsdate(d) -> datetime:
    if d is None:
        return None
    return datetime.fromtimestamp(d.timeIntervalSince1970())


def source_key(cal_id: str, event_id: str, start_ts: float) -> str:
    raw = "%s|%s|%d" % (cal_id, event_id, int(start_ts))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def stable_ident(ev) -> str:
    """Identidade da origem que sobrevive entre instâncias do store.

    `eventIdentifier` é reemitido por Exchange/CalDAV, o que fazia a assinatura
    mudar a cada execução. `calendarItemExternalIdentifier` persiste entre
    dispositivos e entre instâncias — é o que a Apple documenta para isso.
    """
    for getter in ("calendarItemExternalIdentifier", "eventIdentifier",
                   "calendarItemIdentifier"):
        try:
            v = getattr(ev, getter)()
        except Exception:
            continue
        if v:
            return str(v)
    return ""


def marker_of(notes) -> str | None:
    if not notes:
        return None
    m = MARKER_RE.search(str(notes))
    return m.group(1) if m else None


def norm_title(t) -> str:
    return str(t or "").strip().casefold()


def is_mirror_title(ev, titulo) -> bool:
    """True se o título do evento é o título de espelho, ignorando caixa e espaços."""
    want = norm_title(titulo)
    return bool(want) and norm_title(ev.title()) == want


def has_alarms(ev) -> bool:
    try:
        return bool(ev.alarms())
    except Exception:
        return False


def clear_alarms(ev) -> None:
    """Bloco de indisponibilidade não deve notificar nada."""
    try:
        ev.setAlarms_(None)
    except Exception:
        pass


def source_type_of(cal) -> int:
    src = cal.source()
    if src is None or not hasattr(src, "sourceType"):
        return -1
    try:
        return int(src.sourceType())
    except Exception:
        return -1


def is_conta_conectada(cal) -> bool:
    """A fonte local ("Meu Mac") não é conta conectada."""
    return source_type_of(cal) != EK_SRC_LOCAL


def parece_aniversarios(cal) -> bool:
    return norm_title(cal.title()) in NOMES_ANIVERSARIOS


def slot_of(start: datetime, end: datetime) -> tuple:
    """Horário com granularidade de minuto — absorve o drift do round-trip CalDAV."""
    return (int(start.timestamp()) // 60, int(end.timestamp()) // 60)


def intervals_cover(interval, busy_blocks) -> bool:
    """True se busy_blocks cobrem integralmente `interval` (lista de (ini, fim))."""
    start, end = interval
    cursor = start
    for b_start, b_end in sorted(busy_blocks):
        if b_start > cursor:
            return False
        if b_end > cursor:
            cursor = b_end
        if cursor >= end:
            return True
    return cursor >= end


def overlaps(a, b) -> bool:
    return a[0] < b[1] and b[0] < a[1]


# --------------------------------------------------------------------------
# Acesso ao EventKit
# --------------------------------------------------------------------------
def open_store(timeout: float = 60.0):
    store = EventKit.EKEventStore.alloc().init()
    result = {}

    def handler(granted, error):
        result["granted"] = bool(granted)
        result["error"] = error

    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(handler)
    else:
        store.requestAccessToEntityType_completion_(EK_ENTITY_EVENT, handler)

    deadline = time.time() + timeout
    loop = NSRunLoop.currentRunLoop()
    while "granted" not in result and time.time() < deadline:
        loop.runMode_beforeDate_(NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.05))

    if not result.get("granted"):
        err = result.get("error")
        sys.stderr.write(
            "ERRO: acesso ao Calendário negado ou não concedido.\n"
            "Abra Ajustes do Sistema > Privacidade e Segurança > Calendários\n"
            "e autorize o Terminal (e o Python, se aparecer na lista).\n"
            + ("Detalhe: %s\n" % err if err else "")
        )
        sys.exit(3)

    # dá um instante para o store popular as fontes remotas
    store.refreshSourcesIfNecessary() if hasattr(store, "refreshSourcesIfNecessary") else None
    return store


def all_calendars(store):
    return list(store.calendarsForEntityType_(EK_ENTITY_EVENT) or [])


def cal_info(cal) -> dict:
    src = cal.source()
    return {
        "id": str(cal.calendarIdentifier()),
        "nome": str(cal.title()),
        "conta": str(src.title()) if src else "?",
        "tipo": CAL_TYPE_NAMES.get(int(cal.type()), str(cal.type())),
        "tipo_num": int(cal.type()),
        "editavel": bool(cal.allowsContentModifications()),
    }


# --------------------------------------------------------------------------
# Configuração e estado
# --------------------------------------------------------------------------
def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        sys.stderr.write("ERRO: %s não existe. Rode primeiro: unidate.py init\n" % CONFIG_PATH)
        sys.exit(4)
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    return merged


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"mirrors": {}}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("mirrors", {})
        return data
    except Exception:
        return {"mirrors": {}}


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------
def cmd_calendars(args) -> int:
    store = open_store()
    cals = sorted(all_calendars(store), key=lambda c: (str(c.source().title() if c.source() else ""), str(c.title())))
    if not cals:
        print("Nenhuma agenda encontrada.")
        return 0
    print("%-38s  %-28s  %-16s  %-14s  %s" % ("ID", "AGENDA", "CONTA", "TIPO", "EDITÁVEL"))
    print("-" * 118)
    for c in cals:
        i = cal_info(c)
        print("%-38s  %-28s  %-16s  %-14s  %s" % (
            i["id"], i["nome"][:28], i["conta"][:16], i["tipo"], "sim" if i["editavel"] else "NÃO"))
    return 0


def cmd_init(args) -> int:
    if os.path.exists(CONFIG_PATH) and not args.force:
        print("Config já existe em %s (use --force para recriar)." % CONFIG_PATH)
        return 0

    store = open_store()
    cfg = dict(DEFAULT_CONFIG)
    cfg["agendas"] = []
    for c in sorted(all_calendars(store), key=lambda c: str(c.title())):
        cfg["agendas"].append(_entrada_config(c))

    save_json(CONFIG_PATH, cfg)
    print("Config criada em %s" % CONFIG_PATH)
    print("\nAgendas detectadas (origem/destino ligados por padrão nas editáveis):\n")
    by_id = {str(c.calendarIdentifier()): c for c in all_calendars(store)}
    for a in cfg["agendas"]:
        flags = "%s%s" % ("O" if a["origem"] else "-", "D" if a["destino"] else "-")
        c = by_id.get(a["id"])
        if not a["editavel"]:
            motivo = "(somente leitura)"
        elif c is not None and not is_conta_conectada(c):
            motivo = "(fonte local — não é conta conectada)"
        elif c is not None and parece_aniversarios(c):
            motivo = "(agenda de aniversários)"
        elif not a["origem"]:
            motivo = "(tipo de agenda não sincronizável)"
        else:
            motivo = ""
        print("  [%s] %-30s  %-16s  %s" % (flags, a["nome"][:30], a["conta"][:16], motivo))
    print("\nEdite o arquivo para ligar/desligar agendas antes de sincronizar.")
    return 0


def _auto_ligada(cal) -> bool:
    """Regra única de detecção: só agendas editáveis de contas conectadas."""
    return (bool(cal.allowsContentModifications())
            and int(cal.type()) not in (EK_CAL_SUBSCRIPTION, EK_CAL_BIRTHDAY)
            and is_conta_conectada(cal)
            and not parece_aniversarios(cal))


def _entrada_config(cal) -> dict:
    i = cal_info(cal)
    lig = _auto_ligada(cal)
    return {"id": i["id"], "nome": i["nome"], "conta": i["conta"], "tipo": i["tipo"],
            "editavel": i["editavel"], "origem": lig, "destino": lig}


def reconciliar_config(cfg, cals, salvar=True) -> bool:
    """Religa entradas cujo identificador mudou e registra agendas novas.

    Remover e readicionar uma conta troca o identificador da agenda. Sem isto a
    agenda cai fora da malha e só volta com `init --force`, perdendo os ajustes
    manuais. Devolve True se a configuração mudou.
    """
    por_id = {str(c.calendarIdentifier()): c for c in cals}
    usados = {a["id"] for a in cfg["agendas"] if a["id"] in por_id}
    mudou = False

    # 1) entradas órfãs: adota o identificador novo quando há UM único candidato
    #    com mesmo nome e mesma conta. Ambiguidade nunca é resolvida na sorte.
    for a in cfg["agendas"]:
        if a["id"] in por_id:
            continue
        cands = [c for c in cals
                 if str(c.calendarIdentifier()) not in usados
                 and norm_title(c.title()) == norm_title(a.get("nome"))
                 and norm_title(c.source().title() if c.source() else "") == norm_title(a.get("conta"))]
        if len(cands) == 1:
            novo = str(cands[0].calendarIdentifier())
            log("Agenda '%s' (conta '%s') religada: o identificador mudou "
                "(%s -> %s). Provavelmente a conta foi readicionada."
                % (a.get("nome", "?"), a.get("conta", "?"), a["id"], novo))
            a["id"] = novo
            usados.add(novo)
            mudou = True
        elif a.get("origem") or a.get("destino"):
            log("AVISO: a agenda '%s' (conta '%s') da configuração não existe mais "
                "no Calendário%s. Ela está FORA da sincronização. Rode "
                "'init --force' para redetectar."
                % (a.get("nome", "?"), a.get("conta", "?"),
                   " e há %d candidatas com o mesmo nome, então não arrisco escolher"
                   % len(cands) if cands else ""))

    # 2) agendas que apareceram e não estão na configuração
    conhecidos = {a["id"] for a in cfg["agendas"]}
    for c in cals:
        cid = str(c.calendarIdentifier())
        if cid in conhecidos:
            continue
        nova = _entrada_config(c)
        cfg["agendas"].append(nova)
        log("Agenda nova detectada: '%s' (conta '%s') — entrou %s."
            % (nova["nome"], nova["conta"],
               "LIGADA (conta conectada)" if nova["origem"]
               else "desligada (fonte local, aniversários ou somente leitura)"))
        mudou = True

    if mudou and salvar:
        save_json(CONFIG_PATH, cfg)
    return mudou


INTERVALO_MIN_MINUTOS = 5
INTERVALO_MAX_MINUTOS = 1440


def intervalo_segundos(cfg) -> int:
    """Segundos entre ciclos automáticos, a partir de `intervalo_minutos`.

    Piso de 5 minutos de propósito: ciclos mais curtos que isso empilham
    escritas e fazem Google/Exchange rejeitarem em massa, que é o que acende o
    erro de sincronização na conta.
    """
    bruto = cfg.get("intervalo_minutos", 15)
    try:
        minutos = int(bruto)
    except (TypeError, ValueError):
        log("AVISO: intervalo_minutos=%r não é um número; usando 15." % bruto)
        minutos = 15
    limitado = max(INTERVALO_MIN_MINUTOS, min(minutos, INTERVALO_MAX_MINUTOS))
    if limitado != minutos:
        log("AVISO: intervalo_minutos=%s fora da faixa %d-%d; usando %d."
            % (minutos, INTERVALO_MIN_MINUTOS, INTERVALO_MAX_MINUTOS, limitado))
    return limitado * 60


def listar_agendas(store, cfg) -> list:
    """Agendas da máquina com o papel atual de cada uma.

    Serve a interface: quem escolhe as agendas não deveria precisar descobrir o
    identificador de nenhuma. O `id` vem no dado para o menu usar internamente,
    nunca para ser exibido.
    """
    por_id = {a["id"]: a for a in cfg["agendas"]}
    saida = []
    for c in sorted(all_calendars(store),
                    key=lambda c: (str(c.source().title() if c.source() else ""),
                                   str(c.title()))):
        i = cal_info(c)
        a = por_id.get(i["id"], {})
        saida.append({
            "id": i["id"],
            "nome": i["nome"],
            "conta": i["conta"],
            "tipo": i["tipo"],
            "editavel": i["editavel"],
            "origem": bool(a.get("origem", False)),
            "destino": bool(a.get("destino", False)),
            "conhecida": i["id"] in por_id,
            "recomendada": _auto_ligada(c),
        })
    return saida


def definir_papel(cal_id: str, papel: str, valor: bool, cals=None) -> bool:
    """Liga/desliga uma agenda como 'origem' ou 'destino'. True se algo mudou."""
    if papel not in ("origem", "destino"):
        raise ValueError("papel deve ser 'origem' ou 'destino', não %r" % papel)
    cfg = load_config()
    entrada = next((a for a in cfg["agendas"] if a["id"] == cal_id), None)
    if entrada is None:
        # A agenda pode ter aparecido depois do último ciclo: registra na hora,
        # com os dois papéis desligados, e liga só o que foi pedido.
        cal = next((c for c in (cals or []) if str(c.calendarIdentifier()) == cal_id), None)
        if cal is None:
            log("AVISO: agenda %s não encontrada; nada alterado." % cal_id)
            return False
        entrada = _entrada_config(cal)
        entrada["origem"] = entrada["destino"] = False
        cfg["agendas"].append(entrada)
    if papel == "destino" and valor:
        # Prefere perguntar à agenda de verdade: uma config escrita à mão pode
        # não ter o campo, e aí o guarda passaria batido.
        cal = next((c for c in (cals or []) if str(c.calendarIdentifier()) == cal_id), None)
        editavel = (bool(cal.allowsContentModifications()) if cal is not None
                    else entrada.get("editavel", True))
        if not editavel:
            log("AVISO: '%s' é somente leitura e não pode receber blocos."
                % entrada.get("nome", cal_id))
            return False
    if bool(entrada.get(papel)) == bool(valor):
        return False
    entrada[papel] = bool(valor)
    save_json(CONFIG_PATH, cfg)
    log("Agenda '%s': %s %s." % (entrada.get("nome", cal_id), papel,
                                 "ligada" if valor else "desligada"))
    return True


def _selected(cfg, cals):
    by_id = {str(c.calendarIdentifier()): c for c in cals}
    sources, targets = [], []
    for a in cfg["agendas"]:
        c = by_id.get(a["id"])
        if c is None:
            continue   # reconciliar_config() já avisou sobre esta
        if a.get("origem"):
            sources.append(c)
        if a.get("destino"):
            if c.allowsContentModifications():
                targets.append(c)
            else:
                log("AVISO: agenda de destino '%s' é somente leitura — ignorada." % c.title())
    return sources, targets


def _is_syncable(ev, cfg) -> bool:
    if marker_of(ev.notes()):
        return False  # nunca espelhar um espelho
    if is_mirror_title(ev, cfg["titulo_espelho"]):
        return False  # espelho que perdeu a assinatura no servidor
    if ev.isAllDay() and not cfg["incluir_dia_inteiro"]:
        return False
    if cfg["ignorar_cancelados"] and int(ev.status() or 0) == EK_STATUS_CANCELED:
        return False
    if cfg["ignorar_eventos_livres"] and int(ev.availability()) == EK_AVAIL_FREE:
        return False
    if cfg["ignorar_recusados"]:
        for p in (ev.attendees() or []):
            try:
                if p.isCurrentUser() and int(p.participantStatus()) == EK_PART_DECLINED:
                    return False
            except Exception:
                pass
    start, end = from_nsdate(ev.startDate()), from_nsdate(ev.endDate())
    if start is None or end is None or end <= start:
        return False
    minutes = (end - start).total_seconds() / 60.0
    if minutes < cfg["duracao_minima_min"]:
        return False
    if cfg["duracao_maxima_horas"] and minutes > cfg["duracao_maxima_horas"] * 60:
        return False
    return True


def acquire_lock():
    """Trava exclusiva de execução. Devolve o handle, ou None se já há outra instância."""
    d = os.path.dirname(LOCK_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    fh = open(LOCK_PATH, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def release_lock(fh) -> None:
    if fh is None:
        return
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def cmd_sync(args) -> int:
    lock = acquire_lock()
    if lock is None:
        log("Outra execução do unidate está em andamento — saindo.")
        return 0
    try:
        return _sync(args)
    finally:
        release_lock(lock)


def _sync(args) -> int:
    cfg = load_config()
    store = open_store()
    cals = all_calendars(store)
    reconciliar_config(cfg, cals, salvar=not args.dry_run)
    sources, targets = _selected(cfg, cals)

    if not sources or not targets:
        log("Nada a fazer: defina ao menos uma agenda de origem e uma de destino em %s" % CONFIG_PATH)
        return 0

    now = datetime.now()
    win_start = (now - timedelta(days=cfg["dias_atras"])).replace(hour=0, minute=0, second=0, microsecond=0)
    win_end = (now + timedelta(days=cfg["dias_a_frente"])).replace(hour=23, minute=59, second=59, microsecond=0)

    involved = {str(c.calendarIdentifier()): c for c in (sources + targets)}
    pred = store.predicateForEventsWithStartDate_endDate_calendars_(
        to_nsdate(win_start), to_nsdate(win_end), list(involved.values()))
    events = list(store.eventsMatchingPredicate_(pred) or [])

    titulo = cfg["titulo_espelho"]
    target_ids = {str(c.calendarIdentifier()) for c in targets}

    # Um evento é espelho se tem a assinatura OU o título de espelho. A segunda
    # condição é o que segura a cascata quando o servidor descarta as notas.
    # Assinado entra no índice venha de onde vier, para continuar removível se a
    # agenda deixar de ser destino. Só-título entra apenas nas agendas de destino:
    # fora delas não há como distinguir de um evento legítimo do usuário.
    real_by_cal: dict[str, list] = {}
    ocupados_by_slot: dict[tuple, list] = {}
    for ev in events:
        cal = ev.calendar()
        if cal is None:
            continue
        cid = str(cal.calendarIdentifier())
        assinado = marker_of(ev.notes())
        if assinado or is_mirror_title(ev, titulo):
            s, e = from_nsdate(ev.startDate()), from_nsdate(ev.endDate())
            if s and e and (assinado or cid in target_ids):
                ocupados_by_slot.setdefault((cid, slot_of(s, e)), []).append(ev)
            continue
        real_by_cal.setdefault(cid, []).append(ev)

    # blocos ocupados reais por agenda (para a política de sobreposição)
    busy_by_cal: dict[str, list] = {}
    for cid, evs in real_by_cal.items():
        blocks = []
        for ev in evs:
            if ev.isAllDay() and not cfg["incluir_dia_inteiro"]:
                continue
            if int(ev.availability()) == EK_AVAIL_FREE:
                continue
            s, e = from_nsdate(ev.startDate()), from_nsdate(ev.endDate())
            if s and e and e > s:
                blocks.append((s, e))
        busy_by_cal[cid] = blocks

    politica = cfg["politica_sobreposicao"]

    # ---- monta o conjunto desejado de espelhos ----
    # Chave = (destino, slot de minuto). Duas origens no mesmo horário não podem
    # gerar dois blocos: a primeira ganha. A ordem é fixada para que a assinatura
    # gravada não oscile entre execuções.
    desired: dict[tuple, tuple] = {}
    considerados = 0
    for cid in sorted({str(c.calendarIdentifier()) for c in sources}):
        evs = [ev for ev in real_by_cal.get(cid, []) if _is_syncable(ev, cfg)]
        evs.sort(key=lambda e: (from_nsdate(e.startDate()), str(e.eventIdentifier() or "")))
        for ev in evs:
            considerados += 1
            start, end = from_nsdate(ev.startDate()), from_nsdate(ev.endDate())
            key = source_key(cid, stable_ident(ev), start.timestamp())
            piso = cfg.get("duracao_minima_bloco_min") or 0
            if piso:
                end = max(end, start + timedelta(minutes=piso))
            slot = slot_of(start, end)
            for tcal in targets:
                tid = str(tcal.calendarIdentifier())
                if tid == cid or (tid, slot) in desired:
                    continue
                blocks = busy_by_cal.get(tid, [])
                if politica == "qualquer_sobreposicao":
                    if any(overlaps((start, end), b) for b in blocks):
                        continue
                elif politica == "cobertura_total":
                    if intervals_cover((start, end), [b for b in blocks if overlaps((start, end), b)]):
                        continue
                desired[(tid, slot)] = (tcal, start, end, key)

    state = load_state()
    prev = state.get("mirrors", {})
    created = updated = removed = kept = 0
    new_state = {}
    dry = args.dry_run
    teto = int(cfg.get("max_mudancas_por_ciclo") or 0)
    mudancas = 0
    limitado = False

    def _pode_mudar() -> bool:
        """Teto de escritas por ciclo. Simulação não limita: o dry-run existe
        para mostrar o plano inteiro."""
        nonlocal limitado
        if dry or teto <= 0 or mudancas < teto:
            return True
        limitado = True
        return False

    ja_removidos = set()

    def _remover(ev, motivo, cal_name) -> None:
        """Remove um bloco uma única vez. Em simulação nada é apagado de fato, e
        um mesmo bloco pode aparecer em mais de um laço — daí o controle por id."""
        nonlocal removed, mudancas
        if not _pode_mudar():
            return
        eid = str(ev.eventIdentifier() or "")
        if eid:
            if eid in ja_removidos:
                return
            ja_removidos.add(eid)
        s = from_nsdate(ev.startDate())
        if dry:
            log("REMOVER %-9s %-24s %s" % (motivo, cal_name[:24],
                                           s.strftime("%d/%m %H:%M") if s else "?"))
            removed += 1
            return
        ok, err = store.removeEvent_span_commit_error_(ev, EK_SPAN_THIS, True, None)
        if ok:
            removed += 1
            mudancas += 1
        else:
            log("FALHA ao remover em '%s': %s" % (cal_name, err))

    def _pick_survivor(cands, key):
        """Sobrevivente do slot: assinatura exata > qualquer assinatura > só título."""
        for pool in ([e for e in cands if marker_of(e.notes()) == key],
                     [e for e in cands if marker_of(e.notes())],
                     cands):
            if pool:
                return min(pool, key=lambda e: str(e.eventIdentifier() or ""))
        return None

    # ---- criar / atualizar ----
    for (tid, slot), (tcal, start, end, key) in sorted(desired.items(), key=lambda kv: kv[1][1]):
        cands = list(ocupados_by_slot.get((tid, slot), []))
        ev = _pick_survivor(cands, key)
        extras = [e for e in cands if e is not ev]
        if ev is None:
            rec = prev.get("%s|%s" % (tid, key))
            if rec and rec.get("event_id"):
                cand = store.eventWithIdentifier_(rec["event_id"])
                if cand is not None and marker_of(cand.notes()) == key:
                    ev = cand

        if ev is None:
            if not _pode_mudar():
                continue
            if dry:
                log("CRIAR    %-24s %s → %s" % (str(tcal.title())[:24],
                                                start.strftime("%d/%m %H:%M"), end.strftime("%H:%M")))
                created += 1
                continue
            ev = EventKit.EKEvent.eventWithEventStore_(store)
            ev.setCalendar_(tcal)
            ev.setTitle_(titulo)
            ev.setStartDate_(to_nsdate(start))
            ev.setEndDate_(to_nsdate(end))
            ev.setAvailability_(EK_AVAIL_BUSY)
            ev.setNotes_(NOTE_TEMPLATE.format(key=key))
            clear_alarms(ev)
            ok, err = store.saveEvent_span_commit_error_(ev, EK_SPAN_THIS, True, None)
            if not ok:
                log("FALHA ao criar em '%s': %s" % (tcal.title(), err))
                continue
            created += 1
            mudancas += 1
        else:
            cur_s, cur_e = from_nsdate(ev.startDate()), from_nsdate(ev.endDate())
            needs = ((cur_s != start) or (cur_e != end)
                     or (str(ev.title() or "") != titulo)
                     or (marker_of(ev.notes()) != key)
                     # notas no formato antigo: reescreve uma vez. A condição
                     # termina sozinha — depois da reescrita o prefixo está lá,
                     # ao contrário de comparar o texto inteiro, que churnaria
                     # para sempre se um servidor mexesse em espaços.
                     or (MARKER_PREFIX not in str(ev.notes() or ""))
                     or has_alarms(ev))
            if needs and not _pode_mudar():
                kept += 1
            elif needs:
                if dry:
                    log("ATUALIZAR %-23s %s → %s" % (str(tcal.title())[:23],
                                                     start.strftime("%d/%m %H:%M"), end.strftime("%H:%M")))
                    updated += 1
                else:
                    ev.setTitle_(titulo)
                    ev.setStartDate_(to_nsdate(start))
                    ev.setEndDate_(to_nsdate(end))
                    ev.setAvailability_(EK_AVAIL_BUSY)
                    ev.setNotes_(NOTE_TEMPLATE.format(key=key))
                    clear_alarms(ev)
                    ok, err = store.saveEvent_span_commit_error_(ev, EK_SPAN_THIS, True, None)
                    if not ok:
                        log("FALHA ao atualizar em '%s': %s" % (tcal.title(), err))
                        continue
                    updated += 1
                    mudancas += 1
            else:
                kept += 1

        for dup in extras:
            _remover(dup, "(dup)", str(tcal.title()))

        new_state["%s|%s" % (tid, key)] = {
            "event_id": str(ev.eventIdentifier() or "") if not dry else "",
            "calendar": str(tcal.title()),
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

    # ---- órfãos vistos na janela ----
    # Assinados sem origem correspondente saem todos. Sem assinatura, só os
    # excedentes: um bloco solitário pode ser um evento seu e fica intacto.
    for (tid, slot), cands in ocupados_by_slot.items():
        if (tid, slot) in desired:
            continue
        sem_marca = sorted([e for e in cands if not marker_of(e.notes())],
                           key=lambda e: str(e.eventIdentifier() or ""))
        vitimas = [e for e in cands if marker_of(e.notes())] + sem_marca[1:]
        for ev in vitimas:
            cal_name = str(ev.calendar().title()) if ev.calendar() else "?"
            _remover(ev, "(órfão)" if marker_of(ev.notes()) else "(dup)", cal_name)

    # ---- remover órfãos fora da janela, via estado anterior ----
    # Um evento visto na janela já foi julgado pelos laços acima. Removê-lo aqui
    # apagaria o bloco que acabamos de criar ou atualizar — era o que acontecia
    # quando a origem reemitia o identificador e as chaves do estado mudavam.
    ids_na_janela = {str(ev.eventIdentifier() or "")
                     for cands in ocupados_by_slot.values() for ev in cands}
    ids_na_janela.discard("")
    seen = set(new_state.keys())
    for (tid, _slot), cands in ocupados_by_slot.items():
        for ev in cands:
            k = marker_of(ev.notes())
            if k:
                seen.add("%s|%s" % (tid, k))
    for skey, rec in prev.items():
        if skey in seen:
            continue
        eid = rec.get("event_id")
        if not eid or eid in ids_na_janela:
            continue
        ev = store.eventWithIdentifier_(eid)
        if ev is None or marker_of(ev.notes()) is None:
            continue
        _remover(ev, "(fora-jan)", rec.get("calendar", "?"))

    # ---- agendas que deixaram de participar ----
    # Uma agenda desligada (destino: false, tirada da config, ou conta removida)
    # pode ter blocos fora da janela, que os laços acima não alcançam. Varredura
    # ampla, só em assinados: numa agenda que não participa, o título por si não
    # prova posse e o bloco pode ser um evento do usuário.
    # ATENÇÃO: em EventKit, predicado com lista de agendas VAZIA significa TODAS.
    # Sem este guarda, "nenhuma agenda desligada" varreria o calendário inteiro.
    nao_alvo = [c for c in cals if str(c.calendarIdentifier()) not in target_ids]
    if nao_alvo:
        pred_amplo = store.predicateForEventsWithStartDate_endDate_calendars_(
            to_nsdate(now - timedelta(days=730)), to_nsdate(now + timedelta(days=730)), nao_alvo)
        for ev in (store.eventsMatchingPredicate_(pred_amplo) or []):
            if not marker_of(ev.notes()):
                continue
            cal_name = str(ev.calendar().title()) if ev.calendar() else "?"
            _remover(ev, "(deslig.)", cal_name)

    if not dry:
        save_json(STATE_PATH, {"mirrors": new_state, "atualizado_em": datetime.now().isoformat()})

    if limitado:
        log("AVISO: teto de %d mudanças por ciclo atingido — o restante sai no "
            "próximo ciclo. Isso evita que a conta rejeite escrita em massa." % teto)
    log("Origens: %d | Destinos: %d | Compromissos considerados: %d" % (len(sources), len(targets), considerados))
    log("%sCriados: %d | Atualizados: %d | Mantidos: %d | Removidos: %d"
        % ("[SIMULAÇÃO] " if dry else "", created, updated, kept, removed))
    return 0


def cmd_status(args) -> int:
    cfg = load_config()
    store = open_store()
    cals = all_calendars(store)
    _, targets = _selected(cfg, cals)
    now = datetime.now()
    win_start = (now - timedelta(days=cfg["dias_atras"])).replace(hour=0, minute=0, second=0, microsecond=0)
    win_end = now + timedelta(days=cfg["dias_a_frente"])
    if not targets:
        print("Nenhuma agenda de destino configurada.")
        return 0
    pred = store.predicateForEventsWithStartDate_endDate_calendars_(
        to_nsdate(win_start), to_nsdate(win_end), targets)
    counts = {}
    for ev in (store.eventsMatchingPredicate_(pred) or []):
        if marker_of(ev.notes()):
            name = str(ev.calendar().title()) if ev.calendar() else "?"
            counts[name] = counts.get(name, 0) + 1
    print("Espelhos ativos entre %s e %s:" % (win_start.strftime("%d/%m/%Y"), win_end.strftime("%d/%m/%Y")))
    if not counts:
        print("  (nenhum)")
    for name, n in sorted(counts.items()):
        print("  %-32s %d" % (name[:32], n))
    st = load_state()
    print("\nÚltima sincronização: %s" % st.get("atualizado_em", "nunca"))
    return 0


def cmd_purge(args) -> int:
    cfg = load_config()
    store = open_store()
    cals = all_calendars(store)
    now = datetime.now()
    pred = store.predicateForEventsWithStartDate_endDate_calendars_(
        to_nsdate(now - timedelta(days=730)), to_nsdate(now + timedelta(days=730)), cals)
    incluir = bool(getattr(args, "incluir_sem_assinatura", False))
    titulo = cfg["titulo_espelho"]
    victims = []
    for ev in (store.eventsMatchingPredicate_(pred) or []):
        if marker_of(ev.notes()) or (incluir and is_mirror_title(ev, titulo)):
            victims.append(ev)
    if not victims:
        print("Nenhum espelho encontrado.")
        return 0
    if not args.yes:
        print("%d espelhos seriam removidos%s. Rode novamente com --yes para confirmar."
              % (len(victims), " (incluindo os sem assinatura)" if incluir else ""))
        return 0
    n = 0
    for ev in victims:
        ok, _ = store.removeEvent_span_commit_error_(ev, EK_SPAN_THIS, True, None)
        n += 1 if ok else 0
    save_json(STATE_PATH, {"mirrors": {}, "atualizado_em": datetime.now().isoformat()})
    print("Removidos: %d" % n)
    return 0


def cmd_resync(args) -> int:
    """Apaga todos os blocos e reconstrói do zero, num só comando."""
    if not args.yes:
        print("resync apaga todos os blocos '%s' e reconstrói a partir dos seus compromissos."
              % load_config()["titulo_espelho"])
        print("Rode novamente com --yes para confirmar.")
        return 0
    log("=== resync: apagando os blocos existentes ===")
    rc = cmd_purge(args)
    if rc != 0:
        return rc
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
    log("=== resync: reconstruindo ===")
    args.dry_run = False
    return cmd_sync(args)


def main() -> int:
    p = argparse.ArgumentParser(description="Espelha compromissos como blocos Ocupado entre agendas do macOS.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("calendars", help="lista as agendas visíveis")

    p_init = sub.add_parser("init", help="cria o arquivo de configuração")
    p_init.add_argument("--force", action="store_true")

    p_sync = sub.add_parser("sync", help="executa a sincronização")
    p_sync.add_argument("--dry-run", action="store_true", help="mostra o que faria, sem alterar nada")

    sub.add_parser("status", help="estatísticas dos espelhos")

    p_resync = sub.add_parser("resync", help="apaga todos os blocos e sincroniza do zero")
    p_resync.add_argument("--yes", action="store_true")
    p_resync.add_argument("--incluir-sem-assinatura", action="store_true",
                          help="apaga também blocos com o título de espelho sem assinatura")

    p_purge = sub.add_parser("purge", help="remove todos os espelhos criados pelo unidate")
    p_purge.add_argument("--yes", action="store_true")
    p_purge.add_argument("--incluir-sem-assinatura", action="store_true",
                         help="remove também blocos com o título de espelho que perderam a assinatura")

    args = p.parse_args()
    return {
        "calendars": cmd_calendars,
        "init": cmd_init,
        "sync": cmd_sync,
        "status": cmd_status,
        "purge": cmd_purge,
        "resync": cmd_resync,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
