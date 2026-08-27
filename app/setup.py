# -*- coding: utf-8 -*-
"""Empacota o unidate como .app da barra de menus. Use ../build_app.sh."""

from setuptools import setup

VERSAO = "1.0.0"

DESC_CALENDARIO = (
    "O unidate lê seus compromissos para criar blocos genéricos “Ocupado” nas "
    "suas outras agendas, evitando marcações em cima. Título, participantes, "
    "local e notas nunca são copiados, e nada sai do seu Mac."
)

setup(
    app=["unidate_app.py"],
    options={
        "py2app": {
            # argv_emulation usa Carbon e travava apps LSUIElement
            "argv_emulation": False,
            "includes": ["unidate"],
            "packages": ["objc", "Foundation", "AppKit", "EventKit"],
            "plist": {
                "CFBundleName": "unidate",
                "CFBundleDisplayName": "unidate",
                "CFBundleIdentifier": "br.com.mnzs.unidate.app",
                "CFBundleShortVersionString": VERSAO,
                "CFBundleVersion": VERSAO,
                # sem ícone no Dock e sem janela: só barra de menus
                "LSUIElement": True,
                "LSMinimumSystemVersion": "11.0",
                # obrigatórios: sem eles o macOS mata o app ao pedir Calendário
                "NSCalendarsUsageDescription": DESC_CALENDARIO,
                "NSCalendarsFullAccessUsageDescription": DESC_CALENDARIO,
            },
        }
    },
    setup_requires=["py2app"],
)
