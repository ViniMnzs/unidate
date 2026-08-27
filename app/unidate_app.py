#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
unidate.app — ícone na barra de menus do macOS para o unidate.

Camada fina de interface: toda a lógica vive em unidate.py, que tem suíte de
testes própria. Aqui só existe menu, timer e tratamento de erro — nada que
decida o que espelhar.
"""

from __future__ import annotations

import contextlib
import io
import os
import plistlib
import subprocess
import sys
import threading
import traceback
from datetime import datetime

import objc
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSWorkspace,
)
from Foundation import NSObject, NSTimer, NSURL

import unidate

LABEL_LAUNCHAGENT = "br.com.mnzs.unidate"
PLIST_LAUNCHAGENT = os.path.expanduser(
    "~/Library/LaunchAgents/%s.plist" % LABEL_LAUNCHAGENT
)
LOGIN_ITEM_LABEL = "br.com.mnzs.unidate.app"
LOGIN_ITEM_PLIST = os.path.expanduser("~/Library/LaunchAgents/%s.plist" % LOGIN_ITEM_LABEL)
LOG_PATH = os.path.join(unidate.BASE_DIR, "logs", "unidate.log")


# ---------------------------------------------------------------------------
# Execução das operações do unidate
# ---------------------------------------------------------------------------
class Resultado:
    def __init__(self, ok: bool, resumo: str, detalhe: str = ""):
        self.ok, self.resumo, self.detalhe = ok, resumo, detalhe


@contextlib.contextmanager
def _log_para_arquivo():
    """unidate escreve com print(); num .app o stdout não vai a lugar útil."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            yield buf
    finally:
        texto = buf.getvalue()
        if texto:
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(texto)
                if not texto.endswith("\n"):
                    fh.write("\n")


class _Args:
    def __init__(self, **kw):
        self.dry_run = False
        self.force = False
        self.yes = False
        self.incluir_sem_assinatura = False
        self.__dict__.update(kw)


def _executar(fn, args) -> Resultado:
    """unidate usa sys.exit() para erro fatal de CLI — num app isso mataria o processo."""
    try:
        with _log_para_arquivo() as buf:
            fn(args)
        linhas = [l for l in buf.getvalue().splitlines() if l.strip()]
        resumo = next((l.split("] ", 1)[-1] for l in reversed(linhas)
                       if "Criados:" in l or "Removidos:" in l), "")
        return Resultado(True, resumo or (linhas[-1] if linhas else "concluído"))
    except SystemExit as e:
        codigo = e.code if isinstance(e.code, int) else 1
        mensagens = {
            3: "O macOS negou acesso ao Calendário.\n\n"
               "Abra Ajustes do Sistema → Privacidade e Segurança → Calendários "
               "e autorize o unidate.",
            4: "Configuração ausente. Use “Recriar configuração” no menu.",
            2: "PyObjC/EventKit não carregou neste bundle.",
        }
        return Resultado(False, "Falhou (código %s)" % codigo,
                         mensagens.get(codigo, "O unidate encerrou com código %s." % codigo))
    except Exception:
        return Resultado(False, "Erro inesperado", traceback.format_exc(limit=6))


def contar_blocos() -> tuple:
    """(blocos assinados, agendas de destino). Leitura pura."""
    from datetime import timedelta

    cfg = unidate.load_config()
    store = unidate.open_store()
    cals = unidate.all_calendars(store)
    _, destinos = unidate._selected(cfg, cals)
    if not destinos:
        return (0, 0)
    agora = datetime.now()
    ini = (agora - timedelta(days=cfg["dias_atras"])).replace(
        hour=0, minute=0, second=0, microsecond=0)
    fim = agora + timedelta(days=cfg["dias_a_frente"])
    pred = store.predicateForEventsWithStartDate_endDate_calendars_(
        unidate.to_nsdate(ini), unidate.to_nsdate(fim), destinos)
    n = sum(1 for ev in (store.eventsMatchingPredicate_(pred) or [])
            if unidate.marker_of(ev.notes()))
    return (n, len(destinos))


# ---------------------------------------------------------------------------
# Início no login: LaunchAgent apontando para o próprio bundle
# ---------------------------------------------------------------------------
def caminho_do_bundle() -> str | None:
    p = os.path.abspath(sys.argv[0])
    while p not in ("/", ""):
        if p.endswith(".app"):
            return p
        p = os.path.dirname(p)
    return None


def login_ativo() -> bool:
    return os.path.exists(LOGIN_ITEM_PLIST)


def definir_login(ativar: bool) -> None:
    if not ativar:
        subprocess.run(["launchctl", "bootout", "gui/%d/%s" % (os.getuid(), LOGIN_ITEM_LABEL)],
                       capture_output=True)
        if os.path.exists(LOGIN_ITEM_PLIST):
            os.remove(LOGIN_ITEM_PLIST)
        return
    bundle = caminho_do_bundle()
    if not bundle:
        return
    os.makedirs(os.path.dirname(LOGIN_ITEM_PLIST), exist_ok=True)
    with open(LOGIN_ITEM_PLIST, "wb") as fh:
        plistlib.dump({
            "Label": LOGIN_ITEM_LABEL,
            "ProgramArguments": ["/usr/bin/open", "-a", bundle],
            "RunAtLoad": True,
            "ProcessType": "Interactive",
        }, fh)
    subprocess.run(["launchctl", "bootstrap", "gui/%d" % os.getuid(), LOGIN_ITEM_PLIST],
                   capture_output=True)


def launchagent_antigo_ativo() -> bool:
    r = subprocess.run(["launchctl", "print", "gui/%d/%s" % (os.getuid(), LABEL_LAUNCHAGENT)],
                       capture_output=True)
    return r.returncode == 0


def remover_launchagent_antigo() -> None:
    subprocess.run(["launchctl", "bootout", "gui/%d/%s" % (os.getuid(), LABEL_LAUNCHAGENT)],
                   capture_output=True)
    if os.path.exists(PLIST_LAUNCHAGENT):
        os.remove(PLIST_LAUNCHAGENT)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
class UnidateApp(NSObject):

    def init(self):
        self = objc.super(UnidateApp, self).init()
        if self is None:
            return None
        self.ocupado = False
        self._pendente = None
        self.agendas = []          # cache: montar menu não pode abrir o store
        self.ultimo = "ainda não sincronizou"
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength)
        self._icone(False)
        self.menu = NSMenu.alloc().init()
        self.menu.setAutoenablesItems_(False)
        self.item.setMenu_(self.menu)
        self.timer = None
        self.intervalo = 0
        self._reagendar()
        self._montar_menu()
        self.sincronizar_(None)
        return self

    @objc.python_method
    def _reagendar(self) -> None:
        """Aplica `intervalo_minutos` do config.json, relido a cada ciclo."""
        try:
            seg = unidate.intervalo_segundos(unidate.load_config())
        except SystemExit:
            seg = 15 * 60      # config ainda não existe
        if self.timer is not None and seg == self.intervalo:
            return
        if self.timer is not None:
            self.timer.invalidate()
        anterior = self.intervalo
        self.intervalo = seg
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            seg, self, "tickTimer:", None, True)
        with _log_para_arquivo():
            unidate.log("Ciclo automático a cada %d min%s."
                        % (seg // 60,
                           " (era %d)" % (anterior // 60) if anterior else ""))

    # ---------------- aparência
    @objc.python_method
    def _icone(self, trabalhando: bool) -> None:
        nome = "arrow.triangle.2.circlepath" if trabalhando else "calendar.badge.clock"
        img = None
        if hasattr(NSImage, "imageWithSystemSymbolName_accessibilityDescription_"):
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(nome, "unidate")
        if img is not None:
            img.setTemplate_(True)
            self.item.button().setImage_(img)
            self.item.button().setTitle_("")
        else:
            self.item.button().setTitle_("◔" if trabalhando else "◷")

    @objc.python_method
    def _add(self, titulo, sel, key="", ligado=True, marcado=False):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(titulo, sel, key)
        it.setTarget_(self)
        it.setEnabled_(ligado)
        if marcado:
            it.setState_(1)
        self.menu.addItem_(it)
        return it

    @objc.python_method
    def _item(self, menu, titulo, sel, ligado=True, marcado=False, repr_obj=None):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(titulo, sel, "")
        it.setTarget_(self)
        it.setEnabled_(ligado)
        it.setState_(1 if marcado else 0)
        if repr_obj is not None:
            it.setRepresentedObject_(repr_obj)
        menu.addItem_(it)
        return it

    @objc.python_method
    def _cabecalho(self, menu, texto):
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(texto, None, "")
        it.setEnabled_(False)
        menu.addItem_(it)

    @objc.python_method
    def _submenu_papel(self, papel: str):
        """Lista as agendas da máquina agrupadas por conta, marcáveis.

        O usuário escolhe pelo nome da agenda e da conta — o identificador
        nunca aparece, só viaja no representedObject do item.
        """
        sub = NSMenu.alloc().init()
        sub.setAutoenablesItems_(False)
        if not self.agendas:
            self._cabecalho(sub, "Sincronize uma vez para listar as agendas")
            return sub
        conta_atual = None
        for a in self.agendas:
            if a["conta"] != conta_atual:
                if conta_atual is not None:
                    sub.addItem_(NSMenuItem.separatorItem())
                conta_atual = a["conta"]
                self._cabecalho(sub, conta_atual)
            somente_leitura = papel == "destino" and not a["editavel"]
            rotulo = "   %s" % a["nome"]
            if somente_leitura:
                rotulo += "  (somente leitura)"
            self._item(sub, rotulo, "alternarAgenda:",
                       ligado=not somente_leitura and not self.ocupado,
                       marcado=a[papel],
                       repr_obj="%s|%s" % (papel, a["id"]))
        return sub

    @objc.python_method
    def _montar_menu(self) -> None:
        self.menu.removeAllItems()
        livre = not self.ocupado

        cab = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Sincronizando…" if self.ocupado else self.ultimo, None, "")
        cab.setEnabled_(False)
        self.menu.addItem_(cab)
        info = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "a cada %d min · %d agendas ligadas"
            % (self.intervalo // 60,
               sum(1 for a in self.agendas if a["origem"] or a["destino"])),
            None, "")
        info.setEnabled_(False)
        self.menu.addItem_(info)
        self.menu.addItem_(NSMenuItem.separatorItem())

        self._add("Sincronizar agora", "sincronizar:", "s", livre)
        self._add("Re-sincronizar (apaga e reconstrói)…", "resincronizar:", "", livre)
        self._add("Apagar todos os blocos…", "apagar:", "", livre)
        self.menu.addItem_(NSMenuItem.separatorItem())

        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Ler compromissos de…", None, "")
        it.setSubmenu_(self._submenu_papel("origem"))
        self.menu.addItem_(it)
        it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Criar blocos “Ocupado” em…", None, "")
        it.setSubmenu_(self._submenu_papel("destino"))
        self.menu.addItem_(it)
        self.menu.addItem_(NSMenuItem.separatorItem())

        self._add("Abrir configuração", "abrirConfig:")
        self._add("Ver log", "verLog:")
        self._add("Recriar configuração…", "recriarConfig:", "", livre)
        self.menu.addItem_(NSMenuItem.separatorItem())

        self._add("Iniciar no login", "alternarLogin:", "", True, login_ativo())
        if launchagent_antigo_ativo():
            self._add("Desativar agendador antigo (LaunchAgent)…", "desativarAntigo:")
        self.menu.addItem_(NSMenuItem.separatorItem())
        self._add("Sair do unidate", "sair:", "q")

    # ---------------- utilidades de UI
    @objc.python_method
    def _alerta(self, titulo, texto, estilo=1) -> None:
        a = NSAlert.alloc().init()
        a.setMessageText_(titulo)
        a.setInformativeText_(texto)
        a.setAlertStyle_(estilo)
        a.runModal()

    @objc.python_method
    def _confirmar(self, titulo, texto, botao) -> bool:
        a = NSAlert.alloc().init()
        a.setMessageText_(titulo)
        a.setInformativeText_(texto)
        a.setAlertStyle_(2)
        a.addButtonWithTitle_(botao)
        a.addButtonWithTitle_("Cancelar")
        return a.runModal() == NSAlertFirstButtonReturn

    @objc.python_method
    def _iniciar(self, fn, args, rotulo) -> None:
        if self.ocupado:
            return
        self.ocupado = True
        self._icone(True)
        self._montar_menu()

        def trabalho():
            # o resultado vai pelo self: passar tupla Python por
            # performSelectorOnMainThread depende da ponte de objetos
            res = _executar(fn, args)
            self._atualizar_agendas()
            self._pendente = (rotulo, res)
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "terminou:", None, False)

        threading.Thread(target=trabalho, daemon=True).start()

    @objc.python_method
    def _atualizar_agendas(self):
        """Renova o cache de agendas. Roda em thread de fundo, nunca na principal."""
        try:
            with _log_para_arquivo():
                store = unidate.open_store()
                self.agendas = unidate.listar_agendas(store, unidate.load_config())
        except SystemExit:
            pass
        except Exception:
            pass

    def terminou_(self, _):
        pendente, self._pendente = self._pendente, None
        if pendente is None:
            return
        rotulo, res = pendente
        self.ocupado = False
        self._icone(False)
        self._reagendar()
        agora = datetime.now().strftime("%H:%M")
        if res.ok:
            self.ultimo = "%s às %s — %s" % (rotulo, agora, res.resumo or "sem mudanças")
        else:
            self.ultimo = "%s às %s — %s" % (rotulo, agora, res.resumo)
            self._alerta("unidate: %s" % res.resumo, res.detalhe or "Veja o log.", 2)
        self._montar_menu()

    # ---------------- ações do menu
    def tickTimer_(self, _):
        self.sincronizar_(None)

    def sincronizar_(self, _):
        self._iniciar(unidate.cmd_sync, _Args(), "Sincronizado")

    def resincronizar_(self, _):
        if not self._confirmar(
            "Re-sincronizar as agendas?",
            "Todos os blocos “Ocupado” criados pelo unidate serão apagados e "
            "reconstruídos a partir dos seus compromissos.\n\n"
            "Seus compromissos não são alterados.",
            "Re-sincronizar",
        ):
            return
        self._iniciar(unidate.cmd_resync, _Args(yes=True), "Reconstruído")

    def apagar_(self, _):
        if not self._confirmar(
            "Apagar todos os blocos “Ocupado”?",
            "Remove todos os blocos criados pelo unidate. Seus compromissos não "
            "são alterados.\n\nPara sincronizar de novo, use “Sincronizar agora”.",
            "Apagar",
        ):
            return
        self._iniciar(unidate.cmd_purge, _Args(yes=True), "Blocos apagados")

    def recriarConfig_(self, _):
        if not self._confirmar(
            "Recriar a configuração?",
            "Redetecta suas agendas e liga apenas as de contas conectadas — "
            "sem aniversários e sem a fonte local “Meu Mac”.\n\n"
            "Ajustes manuais no config.json serão perdidos.",
            "Recriar",
        ):
            return
        self._iniciar(unidate.cmd_init, _Args(force=True), "Configuração recriada")

    def alternarAgenda_(self, sender):
        try:
            papel, cal_id = str(sender.representedObject()).split("|", 1)
        except Exception:
            return
        atual = next((a for a in self.agendas if a["id"] == cal_id), None)
        if atual is None:
            return
        novo = not atual[papel]
        if papel == "destino" and not novo and atual["destino"]:
            if not self._confirmar(
                "Parar de criar blocos em “%s”?" % atual["nome"],
                "Os blocos “Ocupado” que o unidate criou nessa agenda serão "
                "apagados no próximo ciclo.\n\nSeus compromissos não são tocados.",
                "Parar e apagar",
            ):
                return
        self._iniciar_papel(papel, cal_id, novo)

    @objc.python_method
    def _iniciar_papel(self, papel, cal_id, valor):
        """Grava a escolha e sincroniza, para o efeito ser imediato."""
        if self.ocupado:
            return
        self.ocupado = True
        self._icone(True)
        self._montar_menu()

        def trabalho():
            rot = "Agendas atualizadas"
            try:
                with _log_para_arquivo():
                    store = unidate.open_store()
                    cals = unidate.all_calendars(store)
                    unidate.definir_papel(cal_id, papel, valor, cals=cals)
                res = _executar(unidate.cmd_sync, _Args())
            except SystemExit:
                res = Resultado(False, "Falhou ao gravar a escolha",
                                "Verifique a permissão de Calendário.")
            self._pendente = (rot, res)
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "terminou:", None, False)

        threading.Thread(target=trabalho, daemon=True).start()

    def abrirConfig_(self, _):
        if not os.path.exists(unidate.CONFIG_PATH):
            self._alerta("Configuração ainda não existe",
                         "Use “Recriar configuração” para gerá-la.")
            return
        NSWorkspace.sharedWorkspace().openURL_(
            NSURL.fileURLWithPath_(unidate.CONFIG_PATH))

    def verLog_(self, _):
        if not os.path.exists(LOG_PATH):
            self._alerta("Sem log ainda", "Nenhuma sincronização foi registrada.")
            return
        NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(LOG_PATH))

    def alternarLogin_(self, _):
        definir_login(not login_ativo())
        self._montar_menu()

    def desativarAntigo_(self, _):
        if not self._confirmar(
            "Desativar o agendador antigo?",
            "O LaunchAgent instalado pelo install.sh roda o unidate a cada 15 "
            "minutos por fora do app. Ele não causa conflito — os dois usam a "
            "mesma trava — mas com o app aberto ele é redundante.",
            "Desativar",
        ):
            return
        remover_launchagent_antigo()
        self._montar_menu()

    def sair_(self, _):
        NSApplication.sharedApplication().terminate_(self)


_DELEGATE = None


def main() -> int:
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    global _DELEGATE
    _DELEGATE = UnidateApp.alloc().init()   # NSApplication só guarda referência fraca
    app.setDelegate_(_DELEGATE)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
