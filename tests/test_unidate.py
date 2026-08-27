#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes da lógica do unidate usando stubs de EventKit/Foundation."""
import contextlib
import fcntl
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stub"))
sys.path.insert(0, os.path.dirname(HERE))

import EventKit as EK  # stub
from Foundation import NSDate
import unidate

FAILS = []


def check(cond, label):
    print(("  OK   " if cond else "  FALHA") + "  " + label)
    if not cond:
        FAILS.append(label)


class Args:
    def __init__(self, **kw):
        self.dry_run = False
        self.force = False
        self.yes = False
        self.incluir_sem_assinatura = False
        self.__dict__.update(kw)


def nsd(dt):
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def mk_event(cal, start, end, title="Reuniao", notes=None, allday=False,
             avail=EK.EKEventAvailabilityBusy, status=1, attendees=None):
    e = EK.EKEvent()
    e.setCalendar_(cal)
    e.setTitle_(title)
    e.setStartDate_(nsd(start))
    e.setEndDate_(nsd(end))
    e.setNotes_(notes)
    e.setAllDay_(allday)
    e.setAvailability_(avail)
    e._status = status
    e._attendees = attendees or []
    EK.EKEventStore.events.append(e)
    return e


def mirrors_in(cal_id):
    out = []
    for e in EK.EKEventStore.events:
        if unidate.marker_of(e.notes()) and e.calendar().calendarIdentifier() == cal_id:
            out.append(e)
    return out


def ocupados_in(cal_id, titulo="Ocupado"):
    """Conta blocos pelo TITULO, sem depender da assinatura nas notas."""
    want = titulo.strip().casefold()
    out = []
    for e in EK.EKEventStore.events:
        cal = e.calendar()
        if cal is None or cal.calendarIdentifier() != cal_id:
            continue
        if str(e.title() or "").strip().casefold() == want:
            out.append(e)
    return out


def reset(tmp, politica="cobertura_total", **cfg_over):
    EK.EKEventStore.events = []
    A = EK.Calendar("cal-A", "Pessoal", "iCloud")
    B = EK.Calendar("cal-B", "Trabalho", "Exchange")
    C = EK.Calendar("cal-C", "Consultoria", "Google")
    R = EK.Calendar("cal-R", "Feriados", "Assinatura", ctype=3, writable=False)
    EK.EKEventStore.calendars = [A, B, C, R]

    unidate.BASE_DIR = tmp
    unidate.CONFIG_PATH = os.path.join(tmp, "config.json")
    unidate.STATE_PATH = os.path.join(tmp, "state.json")
    unidate.LOCK_PATH = os.path.join(tmp, "unidate.lock")
    for p in (unidate.CONFIG_PATH, unidate.STATE_PATH):
        if os.path.exists(p):
            os.remove(p)

    cfg = dict(unidate.DEFAULT_CONFIG)
    cfg["politica_sobreposicao"] = politica
    cfg.update(cfg_over)
    cfg["agendas"] = [
        {"id": "cal-A", "nome": "Pessoal", "origem": True, "destino": True},
        {"id": "cal-B", "nome": "Trabalho", "origem": True, "destino": True},
        {"id": "cal-C", "nome": "Consultoria", "origem": True, "destino": True},
        {"id": "cal-R", "nome": "Feriados", "origem": False, "destino": True},
    ]
    unidate.save_json(unidate.CONFIG_PATH, cfg)
    return A, B, C, R


def main():
    tmp = tempfile.mkdtemp()
    base = (datetime.now() + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)

    # ---------------------------------------------------------------- funções puras
    print("\n1) Funções puras")
    t0, t1 = base, base + timedelta(hours=1)
    check(unidate.overlaps((t0, t1), (t0 + timedelta(minutes=30), t1 + timedelta(hours=1))), "sobreposição detectada")
    check(not unidate.overlaps((t0, t1), (t1, t1 + timedelta(hours=1))), "encostado não é sobreposição")
    check(unidate.intervals_cover((t0, t1), [(t0, t1)]), "cobertura exata")
    check(unidate.intervals_cover((t0, t1), [(t0 - timedelta(hours=1), t1 + timedelta(hours=1))]), "cobertura ampla")
    check(unidate.intervals_cover((t0, t1), [(t0, t0 + timedelta(minutes=30)),
                                             (t0 + timedelta(minutes=20), t1)]), "cobertura por dois blocos")
    check(not unidate.intervals_cover((t0, t1), [(t0, t0 + timedelta(minutes=30))]), "cobertura parcial recusada")
    check(not unidate.intervals_cover((t0, t1), []), "sem blocos não cobre")
    check(unidate.marker_of("bla\n[unidate/v1] src=0123456789abcdef") == "0123456789abcdef", "assinatura lida")
    check(unidate.marker_of("reunião normal") is None, "evento normal sem assinatura")
    check(unidate.marker_of(None) is None, "notas vazias")

    # ---------------------------------------------------------------- malha básica
    print("\n2) Malha: 1 compromisso vira Ocupado nas outras 2 agendas editáveis")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Reunião de diretoria confidencial")
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1, "espelho criado em Pessoal")
    check(len(mirrors_in("cal-C")) == 1, "espelho criado em Consultoria")
    check(len(mirrors_in("cal-B")) == 0, "nada criado na própria origem")
    check(len(mirrors_in("cal-R")) == 0, "agenda somente-leitura ignorada")
    m = mirrors_in("cal-A")[0]
    check(m.title() == "Ocupado", "título genérico")
    check("confidencial" not in (m.notes() or ""), "nenhum detalhe vazado")
    check(unidate.from_nsdate(m.startDate()) == base, "horário preservado")

    print("\n3) Idempotência: rodar de novo não duplica")
    unidate.cmd_sync(Args())
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1, "ainda 1 espelho em Pessoal")
    check(len(mirrors_in("cal-C")) == 1, "ainda 1 espelho em Consultoria")

    print("\n4) Sem loop: espelhos não geram espelhos")
    total_antes = len(EK.EKEventStore.events)
    unidate.cmd_sync(Args())
    check(len(EK.EKEventStore.events) == total_antes, "nenhum evento novo (total=%d)" % total_antes)

    print("\n5) Remarcação: espelhos acompanham o novo horário")
    src = [e for e in EK.EKEventStore.events if e.calendar().calendarIdentifier() == "cal-B"][0]
    novo = base + timedelta(hours=4)
    src.setStartDate_(nsd(novo))
    src.setEndDate_(nsd(novo + timedelta(hours=1)))
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1, "continua 1 espelho (antigo removido)")
    check(unidate.from_nsdate(mirrors_in("cal-A")[0].startDate()) == novo, "espelho movido junto")

    print("\n6) Cancelamento: apagar a origem apaga os espelhos")
    EK.EKEventStore.events.remove(src)
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 0 and len(mirrors_in("cal-C")) == 0, "espelhos removidos")

    print("\n7) Filtros")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(days=1), "Férias", allday=True)
    mk_event(B, base, base + timedelta(hours=1), "Almoço livre", avail=EK.EKEventAvailabilityFree)
    mk_event(B, base + timedelta(hours=2), base + timedelta(hours=3), "Cancelada", status=EK.EKEventStatusCanceled)
    mk_event(B, base + timedelta(hours=5), base + timedelta(hours=6), "Recusada",
             attendees=[EK.Attendee(True, EK.EKParticipantStatusDeclined)])
    mk_event(B, base + timedelta(hours=7), base + timedelta(hours=8), "Válida")
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1, "só a reunião válida foi espelhada")
    check(unidate.from_nsdate(mirrors_in("cal-A")[0].startDate()) == base + timedelta(hours=7), "horário correto")

    print("\n8) Política cobertura_total vs qualquer_sobreposicao")
    A, B, C, R = reset(tmp, politica="qualquer_sobreposicao")
    mk_event(B, base, base + timedelta(hours=2), "Workshop")            # 10-12
    mk_event(A, base + timedelta(hours=1), base + timedelta(hours=3), "Dentista")  # 11-13
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 0, "qualquer_sobreposicao: não cria em Pessoal")
    check(len(mirrors_in("cal-B")) == 0, "qualquer_sobreposicao: não cria em Trabalho")
    check(len(mirrors_in("cal-C")) == 2, "ambos espelhados na agenda livre")

    A, B, C, R = reset(tmp, politica="cobertura_total")
    mk_event(B, base, base + timedelta(hours=2), "Workshop")
    mk_event(A, base + timedelta(hours=1), base + timedelta(hours=3), "Dentista")
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1, "cobertura_total: cria em Pessoal (cobertura parcial)")
    check(len(mirrors_in("cal-B")) == 1, "cobertura_total: cria em Trabalho (cobertura parcial)")

    A, B, C, R = reset(tmp, politica="cobertura_total")
    mk_event(B, base, base + timedelta(hours=1), "Reunião")
    mk_event(A, base - timedelta(minutes=30), base + timedelta(hours=2), "Já ocupado")
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 0, "cobertura_total: destino já totalmente ocupado é pulado")

    print("\n9) dry-run não altera nada")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Reunião")
    antes = len(EK.EKEventStore.events)
    unidate.cmd_sync(Args(dry_run=True))
    check(len(EK.EKEventStore.events) == antes, "nenhum evento criado em simulação")
    check(not os.path.exists(unidate.STATE_PATH), "estado não gravado em simulação")

    print("\n10) purge remove só os espelhos")
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1 and len(mirrors_in("cal-C")) == 1, "espelhos presentes")
    unidate.cmd_purge(Args(yes=True))
    restantes = [e for e in EK.EKEventStore.events]
    check(len(restantes) == 1 and restantes[0].title() == "Reunião", "só o compromisso original sobrou")

    print("\n11) Direção: origem sem destino")
    A, B, C, R = reset(tmp)
    cfg = json.load(open(unidate.CONFIG_PATH))
    for a in cfg["agendas"]:
        a["origem"] = a["id"] == "cal-B"
        a["destino"] = a["id"] != "cal-B"
    cfg["agendas"][3]["destino"] = True
    unidate.save_json(unidate.CONFIG_PATH, cfg)
    mk_event(B, base, base + timedelta(hours=1), "Só Trabalho")
    mk_event(A, base + timedelta(hours=6), base + timedelta(hours=7), "Pessoal não espelha")
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1 and len(mirrors_in("cal-C")) == 1, "Trabalho espelhou nas outras")
    check(len(mirrors_in("cal-B")) == 0, "Pessoal não gerou espelho em Trabalho")

    # ------------------------------------------------------------- anti-cascata
    print("\n12.1) Um evento intitulado Ocupado nunca e replicado")
    A, B, C, R = reset(tmp)
    mk_event(A, base, base + timedelta(hours=1), "Ocupado")
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-B")) == 0, "Ocupado sem assinatura nao gerou bloco em Trabalho")
    check(len(ocupados_in("cal-C")) == 0, "Ocupado sem assinatura nao gerou bloco em Consultoria")

    print("\n12.2) Cascata: espelho que perde a assinatura nao gera novos blocos")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 1 and len(ocupados_in("cal-C")) == 1, "1 bloco em cada destino")
    for e in list(EK.EKEventStore.events):
        if e.calendar().calendarIdentifier() == "cal-A" and unidate.marker_of(e.notes()):
            e.setNotes_(None)
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 1, "Pessoal continua com 1 bloco")
    check(len(ocupados_in("cal-C")) == 1, "Consultoria nao recebeu bloco duplicado")
    check(len(ocupados_in("cal-B")) == 0, "a origem nao recebeu bloco")

    print("\n12.3) Unicidade: tres Ocupado no mesmo horario viram um")
    A, B, C, R = reset(tmp)
    for _ in range(3):
        mk_event(A, base, base + timedelta(hours=1), "Ocupado")
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 1, "sobrou exatamente 1 Ocupado em Pessoal")

    print("\n12.4) Corrida de duas execucoes: duplicata com a mesma assinatura e removida")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    orig = mirrors_in("cal-A")[0]
    mk_event(A, unidate.from_nsdate(orig.startDate()), unidate.from_nsdate(orig.endDate()),
             "Ocupado", notes=orig.notes())
    check(len(ocupados_in("cal-A")) == 2, "duplicata semeada")
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 1, "sobrou 1 bloco em Pessoal")
    check(unidate.marker_of(ocupados_in("cal-A")[0].notes()) is not None,
          "o sobrevivente mantem a assinatura")

    print("\n12.5) Cura: bloco sem assinatura no horario desejado e re-estampado")
    A, B, C, R = reset(tmp)
    src = mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    mirrors_in("cal-A")[0].setNotes_(None)
    unidate.cmd_sync(Args())
    sob = ocupados_in("cal-A")
    check(len(sob) == 1 and unidate.marker_of(sob[0].notes()) is not None, "assinatura recuperada")
    EK.EKEventStore.events.remove(src)
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 0, "bloco curado e removido quando a origem morre")

    print("\n12.6) Duas origens no mesmo horario geram um bloco so no destino")
    A, B, C, R = reset(tmp)
    mk_event(A, base, base + timedelta(hours=1), "Reuniao conjunta (pessoal)")
    mk_event(B, base, base + timedelta(hours=1), "Reuniao conjunta (Trabalho)")
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-C")) == 1, "Consultoria recebeu 1 bloco, nao 2")

    print("\n12.7) Caixa e espacos no titulo contam como titulo de espelho")
    A, B, C, R = reset(tmp)
    mk_event(A, base, base + timedelta(hours=1), "ocupado")
    mk_event(A, base + timedelta(hours=3), base + timedelta(hours=4), "  Ocupado  ")
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-B")) == 0, "nenhuma variante replicada para Trabalho")
    check(len(ocupados_in("cal-C")) == 0, "nenhuma variante replicada para Consultoria")

    print("\n12.8) Seguranca: Ocupado solitario do usuario nao e apagado")
    A, B, C, R = reset(tmp)
    mk_event(A, base + timedelta(hours=5), base + timedelta(hours=6), "Ocupado")
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 1, "evento do usuario preservado")

    print("\n12.9) dry-run nao remove duplicatas")
    A, B, C, R = reset(tmp)
    for _ in range(2):
        mk_event(A, base, base + timedelta(hours=1), "Ocupado")
    unidate.cmd_sync(Args(dry_run=True))
    check(len(ocupados_in("cal-A")) == 2, "duplicatas intactas em simulacao")
    check(not os.path.exists(unidate.STATE_PATH), "estado nao gravado em simulacao")

    print("\n12.10) purge --incluir-sem-assinatura")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    mirrors_in("cal-A")[0].setNotes_(None)
    unidate.cmd_purge(Args(yes=True))
    check(len(ocupados_in("cal-A")) == 1, "purge normal nao toca em bloco sem assinatura")
    check(len(ocupados_in("cal-C")) == 0, "purge normal removeu o bloco assinado")
    unidate.cmd_purge(Args(yes=True, incluir_sem_assinatura=True))
    check(len(ocupados_in("cal-A")) == 0, "purge com flag removeu o bloco sem assinatura")
    restantes = sorted(str(e.title()) for e in EK.EKEventStore.events)
    check(restantes == ["Diretoria"], "compromisso real preservado (sobrou: %s)" % restantes)

    print("\n12.11) Lock: execucao concorrente nao faz nada")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    holder = open(unidate.LOCK_PATH, "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    rc = unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 0, "nada criado enquanto outra instancia roda")
    check(rc == 0, "saida silenciosa, sem erro para o launchd (rc=%s)" % rc)
    fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
    holder.close()
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 1, "apos liberar o lock, sincroniza normalmente")

    print("\n12.12) Agenda que deixa de ser destino tem os blocos antigos removidos")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 1, "bloco criado em Pessoal")
    cfg = json.load(open(unidate.CONFIG_PATH))
    for a in cfg["agendas"]:
        if a["id"] == "cal-A":
            a["destino"] = False
    unidate.save_json(unidate.CONFIG_PATH, cfg)
    # sem o state.json: a assinatura tem de bastar, como manda o desenho do README
    os.remove(unidate.STATE_PATH)
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 0, "bloco removido depois de desligar o destino")
    check(len(ocupados_in("cal-C")) == 1, "Consultoria segue com o bloco dela")

    print("\n12.13) init liga so agendas de conta conectada, sem aniversarios")
    EK.EKEventStore.events = []
    EK.EKEventStore.calendars = [
        EK.Calendar("c-loc", "Calendário", "Default", stype=EK.EKSourceTypeLocal),
        EK.Calendar("c-anv", "Aniversários", "Empresa", stype=EK.EKSourceTypeExchange),
        EK.Calendar("c-exc", "Calendário", "Empresa", stype=EK.EKSourceTypeExchange),
        EK.Calendar("c-dav", "Trabalho", "contato@exemplo.com", stype=EK.EKSourceTypeCalDAV),
    ]
    unidate.CONFIG_PATH = os.path.join(tmp, "config-init.json")
    if os.path.exists(unidate.CONFIG_PATH):
        os.remove(unidate.CONFIG_PATH)
    unidate.cmd_init(Args(force=True))
    liga = {a["id"]: (a["origem"], a["destino"])
            for a in json.load(open(unidate.CONFIG_PATH))["agendas"]}
    check(liga["c-loc"] == (False, False), "fonte local (Meu Mac) fica desligada")
    check(liga["c-anv"] == (False, False), "agenda de aniversarios fica desligada")
    check(liga["c-exc"] == (True, True), "Exchange conectada fica ligada")
    check(liga["c-dav"] == (True, True), "CalDAV conectada fica ligada")

    print("\n12.14) Agenda desligada: blocos apagados tambem FORA da janela")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1, "bloco em Pessoal dentro da janela")
    passado = datetime.now() - timedelta(days=200)
    mk_event(A, passado, passado + timedelta(hours=1), "Ocupado",
             notes=unidate.NOTE_TEMPLATE.format(key="dead000000000000"))
    check(len(ocupados_in("cal-A")) == 2, "bloco antigo fora da janela semeado")
    cfg = json.load(open(unidate.CONFIG_PATH))
    for a in cfg["agendas"]:
        if a["id"] == "cal-A":
            a["origem"] = a["destino"] = False
    unidate.save_json(unidate.CONFIG_PATH, cfg)
    os.remove(unidate.STATE_PATH)   # a assinatura tem de bastar
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 0, "Pessoal zerada, dentro e fora da janela")
    check(len(ocupados_in("cal-C")) == 1, "Consultoria segue com o bloco dela")

    print("\n12.15) Varredura nao toca bloco SEM assinatura em agenda desligada")
    A, B, C, R = reset(tmp)
    passado = datetime.now() - timedelta(days=200)
    meu = mk_event(A, passado, passado + timedelta(hours=1), "Ocupado")
    cfg = json.load(open(unidate.CONFIG_PATH))
    for a in cfg["agendas"]:
        if a["id"] == "cal-A":
            a["origem"] = a["destino"] = False
    unidate.save_json(unidate.CONFIG_PATH, cfg)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    check(meu in EK.EKEventStore.events, "bloco sem assinatura preservado na agenda desligada")

    print("\n12.16) Bloco tem duracao minima de 30 min")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(minutes=15), "Daily de 15 min")
    unidate.cmd_sync(Args())
    m = mirrors_in("cal-A")
    check(len(m) == 1, "bloco criado")
    ini, fim = unidate.from_nsdate(m[0].startDate()), unidate.from_nsdate(m[0].endDate())
    check(ini == base, "inicio preservado")
    check(fim - ini == timedelta(minutes=30), "bloco de 15 min estendido para 30 (deu %s)" % (fim - ini))

    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=2), "Workshop")
    unidate.cmd_sync(Args())
    m = mirrors_in("cal-A")[0]
    dur = unidate.from_nsdate(m.endDate()) - unidate.from_nsdate(m.startDate())
    check(dur == timedelta(hours=2), "evento de 2h nao e encurtado nem esticado (deu %s)" % dur)

    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(minutes=15), "Daily")
    mk_event(C, base, base + timedelta(minutes=20), "Outra curta")
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 1, "dois eventos curtos no mesmo inicio viram 1 bloco de 30 min")

    A, B, C, R = reset(tmp, duracao_minima_bloco_min=0)
    mk_event(B, base, base + timedelta(minutes=15), "Daily")
    unidate.cmd_sync(Args())
    m = mirrors_in("cal-A")[0]
    dur = unidate.from_nsdate(m.endDate()) - unidate.from_nsdate(m.startDate())
    check(dur == timedelta(minutes=15), "com o minimo em 0 o bloco fica de 15 min (deu %s)" % dur)

    print("\n12.17) Simulacao nao conta o mesmo bloco duas vezes")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1, "bloco em Pessoal")
    cfg = json.load(open(unidate.CONFIG_PATH))
    for a in cfg["agendas"]:
        if a["id"] == "cal-A":
            a["origem"] = a["destino"] = False
    unidate.save_json(unidate.CONFIG_PATH, cfg)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        unidate.cmd_sync(Args(dry_run=True))
    saida = buf.getvalue()
    n_rem = sum(1 for l in saida.splitlines() if "REMOVER" in l)
    total = [l for l in saida.splitlines() if "Removidos:" in l]
    check(n_rem == 1, "o bloco aparece 1 vez no log, nao 2 (apareceu %d)" % n_rem)
    check("Removidos: 1 " in total[-1] or total[-1].rstrip().endswith("Removidos: 1"),
          "contador diz 1 (linha: %s)" % (total[-1].split("] ", 1)[-1] if total else "?"))
    check(len(mirrors_in("cal-A")) == 1, "simulacao nao apagou nada")

    print("\n12.18) Bloco nunca tem alarme")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    m = mirrors_in("cal-A")[0]
    check(not m.alarms(), "bloco criado sem alarme")
    m.setAlarms_(["alarme-injetado-pelo-servidor"])
    check(bool(m.alarms()), "alarme semeado no bloco existente")
    unidate.cmd_sync(Args())
    check(not mirrors_in("cal-A")[0].alarms(), "alarme retirado no ciclo seguinte")

    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    m = mirrors_in("cal-A")[0]
    m.setAlarms_(["x"])
    unidate.cmd_sync(Args(dry_run=True))
    check(bool(mirrors_in("cal-A")[0].alarms()), "simulacao nao altera o alarme")

    print("\n12.19) resync apaga tudo e reconstroi")
    A, B, C, R = reset(tmp)
    real = mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    antes = sorted(e.eventIdentifier() for e in mirrors_in("cal-A"))
    check(len(antes) == 1, "bloco existe antes do resync")
    unidate.cmd_resync(Args(yes=True))
    depois = sorted(e.eventIdentifier() for e in mirrors_in("cal-A"))
    check(len(depois) == 1, "bloco reconstruido")
    check(depois != antes, "o bloco e novo, nao o antigo reaproveitado")
    check(real in EK.EKEventStore.events, "compromisso real intacto")

    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    ids = sorted(e.eventIdentifier() for e in mirrors_in("cal-A"))
    unidate.cmd_resync(Args())
    check(sorted(e.eventIdentifier() for e in mirrors_in("cal-A")) == ids,
          "resync sem --yes nao mexe em nada")

    print("\n12.20) Identificador instavel na origem nao destroi os blocos")
    A, B, C, R = reset(tmp)
    src = mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    ids_antes = sorted(e.eventIdentifier() for e in mirrors_in("cal-A") + mirrors_in("cal-C"))
    check(len(ids_antes) == 2, "2 blocos criados")
    src._id = "evt-reemitido-pelo-servidor"   # Exchange/CalDAV fazem isso
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1, "Pessoal segue com 1 bloco")
    check(len(mirrors_in("cal-C")) == 1, "Consultoria segue com 1 bloco")
    ids_depois = sorted(e.eventIdentifier() for e in mirrors_in("cal-A") + mirrors_in("cal-C"))
    check(ids_depois == ids_antes, "os MESMOS eventos foram reaproveitados, nao recriados")
    unidate.cmd_sync(Args())
    check(sorted(e.eventIdentifier() for e in mirrors_in("cal-A") + mirrors_in("cal-C")) == ids_antes,
          "ciclo seguinte tambem estavel")

    print("\n12.21) Assinatura vem do identificador externo, estavel")
    A, B, C, R = reset(tmp)
    src = mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    marca = unidate.marker_of(mirrors_in("cal-A")[0].notes())
    src._id = "outro-id-interno"
    unidate.cmd_sync(Args())
    check(unidate.marker_of(mirrors_in("cal-A")[0].notes()) == marca,
          "assinatura nao muda quando so o id interno muda")

    print("\n12.22) Assinatura antiga [calsync/v1] continua reconhecida")
    check(unidate.marker_of("x\n[unidate/v1] src=0123456789abcdef") == "0123456789abcdef",
          "assinatura nova lida")
    check(unidate.marker_of("x\n[calsync/v1] src=0123456789abcdef") == "0123456789abcdef",
          "assinatura ANTIGA lida")
    check("[unidate/v1]" in unidate.NOTE_TEMPLATE, "blocos novos usam a assinatura nova")

    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    antigo = mk_event(A, base, base + timedelta(hours=1), "Ocupado",
                      notes="Bloco antigo\n[calsync/v1] src=dead000000000000")
    unidate.cmd_sync(Args())
    sob = ocupados_in("cal-A")
    check(len(sob) == 1, "1 bloco em Pessoal")
    check(sob[0] is antigo, "o bloco ANTIGO foi adotado, nao recriado")
    check("[unidate/v1]" in (sob[0].notes() or ""), "re-estampado com a assinatura nova")

    # blocos antigos fora da janela ainda tem de ser reconheciveis pelo purge,
    # porque nunca serao re-estampados
    A, B, C, R = reset(tmp)
    passado = datetime.now() - timedelta(days=200)
    mk_event(A, passado, passado + timedelta(hours=1), "Ocupado",
             notes="[calsync/v1] src=beef000000000000")
    unidate.cmd_purge(Args(yes=True))
    check(len(ocupados_in("cal-A")) == 0, "purge alcanca bloco antigo fora da janela")

    print("\n12.23) Notas antigas sao reescritas uma vez, e so uma vez")
    A, B, C, R = reset(tmp)
    src = mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    # bloco com a MESMA chave que o sync vai calcular, mas no formato antigo
    key = unidate.source_key("cal-B", unidate.stable_ident(src), base.timestamp())
    velho = mk_event(A, base, base + timedelta(hours=1), "Ocupado",
                     notes="Bloco automatico.\nCriado e mantido por calsync\n"
                           "[calsync/v1] src=" + key)
    unidate.cmd_sync(Args())
    notas = ocupados_in("cal-A")[0].notes() or ""
    check(ocupados_in("cal-A")[0] is velho, "o mesmo evento foi reaproveitado")
    check("[unidate/v1]" in notas, "assinatura reescrita para o formato novo")
    check("calsync" not in notas, "texto antigo sumiu das notas")

    # e nao pode reescrever para sempre: o ciclo seguinte tem de achar tudo em ordem
    notas_apos = ocupados_in("cal-A")[0].notes()
    unidate.cmd_sync(Args())
    check(ocupados_in("cal-A")[0].notes() == notas_apos, "ciclo seguinte nao mexe nas notas")
    unidate.cmd_sync(Args())
    check(ocupados_in("cal-A")[0].notes() == notas_apos, "e nem o terceiro (sem churn eterno)")

    print("\n12.24) Agenda da config que sumiu do store grita no log")
    A, B, C, R = reset(tmp)
    cfg = json.load(open(unidate.CONFIG_PATH))
    cfg["agendas"].append({"id": "cal-FANTASMA", "nome": "Trabalho", "conta": "Trabalho",
                           "origem": True, "destino": True})
    unidate.save_json(unidate.CONFIG_PATH, cfg)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        unidate.cmd_sync(Args())
    saida = buf.getvalue()
    check("AVISO" in saida, "sai como AVISO")
    check("Trabalho" in saida, "o aviso nomeia a agenda que sumiu")
    check("init --force" in saida, "o aviso diz o que fazer")

    print("\n12.25) Limite de mudancas por ciclo evita rajada contra o servidor")
    A, B, C, R = reset(tmp, max_mudancas_por_ciclo=5)
    for i in range(10):
        ini = base + timedelta(hours=i)
        mk_event(B, ini, ini + timedelta(minutes=30), "Reuniao %d" % i)
    unidate.cmd_sync(Args())
    n1 = len(ocupados_in("cal-A")) + len(ocupados_in("cal-C"))
    check(n1 <= 5, "primeiro ciclo fez no maximo 5 mudancas (fez %d)" % n1)
    check(n1 > 0, "mas fez alguma coisa")
    for _ in range(12):
        unidate.cmd_sync(Args())
    n2 = len(ocupados_in("cal-A")) + len(ocupados_in("cal-C"))
    check(n2 == 20, "converge para 20 blocos ao longo dos ciclos (deu %d)" % n2)

    A, B, C, R = reset(tmp)
    check(unidate.DEFAULT_CONFIG.get("max_mudancas_por_ciclo", 0) > 0,
          "existe um limite padrao")
    for i in range(3):
        ini = base + timedelta(hours=i)
        mk_event(B, ini, ini + timedelta(minutes=30), "Reuniao %d" % i)
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 3, "operacao normal nao encosta no limite padrao")

    print("\n12.26) Conta readicionada: o ID novo e adotado sozinho")
    A, B, C, R = reset(tmp)
    cfg = json.load(open(unidate.CONFIG_PATH))
    # simula readicao da conta: mesmo nome e conta, ID novo
    for a in cfg["agendas"]:
        if a["id"] == "cal-A":
            a["id"] = "cal-A-ID-ANTIGO"
            a["nome"] = "Pessoal"
            a["conta"] = "iCloud"
    unidate.save_json(unidate.CONFIG_PATH, cfg)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        unidate.cmd_sync(Args())
    saida = buf.getvalue()
    check("cal-A" in saida or "Pessoal" in saida, "o log menciona a agenda religada")
    check(len(mirrors_in("cal-A")) == 1, "a agenda voltou a receber blocos sozinha")
    novo = {a["nome"]: a["id"] for a in json.load(open(unidate.CONFIG_PATH))["agendas"]}
    check(novo.get("Pessoal") == "cal-A", "config foi reescrita com o ID novo (%s)" % novo.get("Pessoal"))

    print("\n12.27) Agenda nova de conta conectada entra sozinha")
    A, B, C, R = reset(tmp)
    cfg = json.load(open(unidate.CONFIG_PATH))
    cfg["agendas"] = [a for a in cfg["agendas"] if a["id"] != "cal-C"]
    unidate.save_json(unidate.CONFIG_PATH, cfg)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    ids = {a["id"]: a for a in json.load(open(unidate.CONFIG_PATH))["agendas"]}
    check("cal-C" in ids, "a agenda ausente foi adicionada a config")
    check(ids.get("cal-C", {}).get("destino") is True, "e entrou ligada (conta conectada)")
    check(len(mirrors_in("cal-C")) == 1, "e ja recebeu bloco no mesmo ciclo")

    print("\n12.28) Agenda nova de fonte local entra DESLIGADA")
    A, B, C, R = reset(tmp)
    LOC = EK.Calendar("cal-LOC", "Meu Mac", "Default", stype=EK.EKSourceTypeLocal)
    EK.EKEventStore.calendars.append(LOC)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    ids = {a["id"]: a for a in json.load(open(unidate.CONFIG_PATH))["agendas"]}
    check("cal-LOC" in ids, "a agenda local foi registrada na config")
    check(ids.get("cal-LOC", {}).get("destino") is False, "mas DESLIGADA")
    check(len(ocupados_in("cal-LOC")) == 0, "e nao recebeu bloco")

    print("\n12.29) Ambiguidade nao e adotada as cegas")
    A, B, C, R = reset(tmp)
    # duas agendas com mesmo nome e mesma conta: nao ha como escolher
    EK.EKEventStore.calendars.append(EK.Calendar("cal-X1", "Duplicada", "ContaZ"))
    EK.EKEventStore.calendars.append(EK.Calendar("cal-X2", "Duplicada", "ContaZ"))
    cfg = json.load(open(unidate.CONFIG_PATH))
    cfg["agendas"].append({"id": "cal-X-ANTIGO", "nome": "Duplicada", "conta": "ContaZ",
                           "origem": True, "destino": True})
    unidate.save_json(unidate.CONFIG_PATH, cfg)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        unidate.cmd_sync(Args())
    saida = buf.getvalue()
    check("AVISO" in saida, "avisa em vez de adivinhar")
    ids = {a["id"] for a in json.load(open(unidate.CONFIG_PATH))["agendas"]}
    check("cal-X-ANTIGO" in ids, "a entrada ambigua nao foi religada as cegas")

    print("\n12.30) listar_agendas: o que a interface mostra")
    A, B, C, R = reset(tmp)
    store = EK.EKEventStore.alloc().init()
    lista = unidate.listar_agendas(store, unidate.load_config())
    por_nome = {a["nome"]: a for a in lista}
    check(len(lista) == 4, "lista as 4 agendas da maquina (deu %d)" % len(lista))
    check(por_nome["Pessoal"]["conta"] == "iCloud", "traz o nome da conta para o usuario se achar")
    check(por_nome["Pessoal"]["origem"] is True, "traz o papel atual de origem")
    check(por_nome["Feriados"]["editavel"] is False, "marca a somente-leitura")
    check(all("id" in a for a in lista), "o id existe no dado, mas e a interface que esconde")

    print("\n12.31) definir_papel: desligar destino para de criar e limpa")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1, "bloco criado em Pessoal")
    check(unidate.definir_papel("cal-A", "destino", False) is True, "definir_papel devolve que mudou")
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 0, "bloco removido depois de desligar o destino")
    check(len(mirrors_in("cal-C")) == 1, "Consultoria segue intacta")

    print("\n12.32) definir_papel: religar volta a criar")
    check(unidate.definir_papel("cal-A", "destino", True) is True, "religou")
    unidate.cmd_sync(Args())
    check(len(mirrors_in("cal-A")) == 1, "bloco voltou")
    check(unidate.definir_papel("cal-A", "destino", True) is False, "sem mudanca devolve False")

    print("\n12.33) definir_papel: origem desligada para de espelhar")
    A, B, C, R = reset(tmp)
    mk_event(B, base, base + timedelta(hours=1), "Diretoria")
    unidate.definir_papel("cal-B", "origem", False)
    unidate.cmd_sync(Args())
    check(len(ocupados_in("cal-A")) == 0 and len(ocupados_in("cal-C")) == 0,
          "nada espelhado com a origem desligada")

    print("\n12.34) definir_papel: somente-leitura nao pode ser destino")
    A, B, C, R = reset(tmp)
    cals_r = unidate.all_calendars(EK.EKEventStore.alloc().init())
    unidate.definir_papel("cal-R", "destino", False, cals=cals_r)   # parte do zero
    check(unidate.definir_papel("cal-R", "destino", True, cals=cals_r) is False,
          "recusa ligar destino em agenda somente-leitura")
    cfgR = {a["id"]: a for a in json.load(open(unidate.CONFIG_PATH))["agendas"]}
    check(cfgR["cal-R"]["destino"] is False, "e a config continua desligada")
    # e o guarda tem de valer mesmo sem o campo 'editavel' gravado
    cfg2 = json.load(open(unidate.CONFIG_PATH))
    for a in cfg2["agendas"]:
        a.pop("editavel", None)
    unidate.save_json(unidate.CONFIG_PATH, cfg2)
    check(unidate.definir_papel("cal-R", "destino", True, cals=cals_r) is False,
          "recusa mesmo sem o campo 'editavel' na config")

    print("\n12.35) definir_papel: agenda que nao esta na config e registrada")
    A, B, C, R = reset(tmp)
    NOVA = EK.Calendar("cal-NOVA", "Recem-adicionada", "ContaNova")
    EK.EKEventStore.calendars.append(NOVA)
    cals = unidate.all_calendars(EK.EKEventStore.alloc().init())
    check(unidate.definir_papel("cal-NOVA", "destino", True, cals=cals) is True,
          "aceita agenda ainda nao registrada")
    cfgN = {a["id"]: a for a in json.load(open(unidate.CONFIG_PATH))["agendas"]}
    check("cal-NOVA" in cfgN, "entrada criada na config")
    check(cfgN["cal-NOVA"]["destino"] is True and cfgN["cal-NOVA"]["origem"] is False,
          "so o papel pedido foi ligado")

    print("\n12.36) definir_papel: papel invalido e erro, nao silencio")
    erro = False
    try:
        unidate.definir_papel("cal-A", "banana", True)
    except ValueError:
        erro = True
    check(erro, "papel invalido levanta ValueError")

    print("\n12.37) intervalo_minutos no config.json")
    f = unidate.intervalo_segundos
    check(f({}) == 15 * 60, "sem a chave, cai no padrao de 15 min")
    check(f({"intervalo_minutos": 30}) == 1800, "30 min -> 1800s")
    check(f({"intervalo_minutos": 5}) == 300, "5 min aceito (piso)")
    check(f({"intervalo_minutos": 1}) == 300, "1 min e elevado ao piso de 5")
    check(f({"intervalo_minutos": 0}) == 300, "0 e elevado ao piso")
    check(f({"intervalo_minutos": -10}) == 300, "negativo e elevado ao piso")
    check(f({"intervalo_minutos": 99999}) == 1440 * 60, "acima de 1 dia e limitado")
    check(f({"intervalo_minutos": "abc"}) == 15 * 60, "valor invalido cai no padrao")
    check(f({"intervalo_minutos": None}) == 15 * 60, "nulo cai no padrao")
    check(f({"intervalo_minutos": "45"}) == 2700, "string numerica e aceita")
    check(unidate.DEFAULT_CONFIG.get("intervalo_minutos") == 15, "padrao documentado na config")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 60)
    if FAILS:
        print("FALHAS (%d):" % len(FAILS))
        for f in FAILS:
            print("  - " + f)
        return 1
    print("Todos os testes passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
