#!/bin/bash
# ---------------------------------------------------------------------------
# unidate — monta o .app da barra de menus.
#
# Cria um venv isolado em build/venv (não mexe no seu Python nem no
# ~/.unidate), instala py2app + PyObjC ali dentro e gera
# dist/unidate.app.
# ---------------------------------------------------------------------------
set -euo pipefail

INSTALAR=0
for arg in "$@"; do
  case "$arg" in
    --install) INSTALAR=1 ;;
    -h|--help) echo "uso: build_app.sh [--install]"; exit 0 ;;
    *) echo "argumento desconhecido: $arg" >&2; echo "uso: build_app.sh [--install]" >&2; exit 2 ;;
  esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SRC/build/venv"
cd "$SRC"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Só roda no macOS." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Python: py2app precisa de 3.9+; preferimos o mais novo disponível
# ---------------------------------------------------------------------------
PY=""
for p in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
         /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 \
         /usr/local/bin/python3.13 /usr/local/bin/python3.12 \
         /usr/local/bin/python3.11 /usr/local/bin/python3 \
         /usr/bin/python3; do
  [[ -x "$p" ]] || continue
  ver="$("$p" -c 'import sys;print("%d%02d"%sys.version_info[:2])' 2>/dev/null)" || continue
  if (( ver >= 309 )); then PY="$p"; break; fi
done
if [[ -z "$PY" ]]; then
  echo "Nenhum Python 3.9+ encontrado. Instale com: brew install python@3.12" >&2
  exit 1
fi
echo "==> Python de build: $PY ($("$PY" -V 2>&1))"

# ---------------------------------------------------------------------------
# Venv isolado
# ---------------------------------------------------------------------------
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "==> Criando venv em build/venv"
  "$PY" -m venv "$VENV"
fi
VPY="$VENV/bin/python"

# Um "user = true" no pip.conf (ou PIP_USER no ambiente) quebra pip dentro de
# venv com "Can not perform a '--user' install". PIP_USER=0 neutraliza sem
# descartar o resto da sua configuração (índice interno, proxy etc.).
pip_venv() {
  if ! env PIP_USER=0 "$VPY" -m pip install --quiet --disable-pip-version-check "$@"; then
    echo "    Repetindo sem ler nenhum pip.conf."
    env PIP_CONFIG_FILE=/dev/null PIP_USER=0 "$VPY" -m pip install \
      --quiet --disable-pip-version-check "$@"
  fi
}

echo "==> Instalando py2app e PyObjC no venv (não afeta seu Python)"
pip_venv --upgrade pip setuptools wheel
pip_venv py2app pyobjc-framework-Cocoa pyobjc-framework-EventKit

"$VPY" -c 'import EventKit, AppKit, py2app; print("    imports OK")'

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
echo "==> Publicando unidate.py dentro de app/"
cp "$SRC/unidate.py" "$SRC/app/unidate.py"

# Porta obrigatória: importar o módulo dispara a transformação de classe do
# PyObjC, que é onde erros de prototipagem de selector aparecem. Buildar sem
# isso produz um .app que abre e morre.
echo "==> Conferindo o módulo do app (transformação de classe do PyObjC)"
( cd "$SRC/app" && "$VPY" -c 'import unidate_app; print("    módulo OK")' )

echo "==> Limpando saídas anteriores"
rm -rf "$SRC/dist" "$SRC/app/build" "$SRC/app/dist"

echo "==> Empacotando"
mkdir -p "$SRC/build"
( cd "$SRC/app" && "$VPY" setup.py py2app --dist-dir "$SRC/dist" ) \
  > "$SRC/build/py2app.log" 2>&1 || {
    echo "    py2app falhou; veja build/py2app.log" >&2
    tail -30 "$SRC/build/py2app.log" >&2
    exit 1
  }

APP="$SRC/dist/unidate.app"
[[ -d "$APP" ]] || { echo "Build não produziu $APP" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Conferências: sem elas o app abre e morre na primeira permissão
# ---------------------------------------------------------------------------
echo "==> Conferindo o bundle"
PL="$APP/Contents/Info.plist"
for chave in LSUIElement NSCalendarsUsageDescription NSCalendarsFullAccessUsageDescription; do
  if /usr/libexec/PlistBuddy -c "Print :$chave" "$PL" >/dev/null 2>&1; then
    echo "    $chave OK"
  else
    echo "    FALTA $chave no Info.plist" >&2
    exit 1
  fi
done

# assinatura ad-hoc: sem isso o macOS reclama do bundle já na primeira abertura
echo "==> Assinando (ad-hoc)"
codesign --force --deep --sign - "$APP" 2>/dev/null || \
  echo "    aviso: codesign ad-hoc falhou; o app ainda abre com clique-direito → Abrir"

if [[ $INSTALAR -eq 1 ]]; then
  echo "==> Instalando em /Applications"
  # encerra a instância em uso: sobrescrever um bundle aberto deixa o app num
  # estado meio-antigo meio-novo até o próximo relançamento
  pkill -f "/Applications/unidate.app/Contents/MacOS/unidate" 2>/dev/null || true
  sleep 1
  # cp -R sobre um bundle existente MESCLA, deixando arquivos velhos para trás
  rm -rf "/Applications/unidate.app"
  cp -R "$APP" /Applications/
  echo "    /Applications/unidate.app"
  open -a /Applications/unidate.app
  echo "    aberto — procure o ícone na barra de menus"
fi

TAM="$(du -sh "$APP" | cut -f1)"
cat <<EOF

================================================================
Pronto: dist/unidate.app  ($TAM)

Instalar (ou rode: ./build_app.sh --install):
    cp -R dist/unidate.app /Applications/
    open /Applications/unidate.app

Na primeira abertura o macOS pede acesso ao Calendário — aceite.
O ícone aparece na barra de menus (não vai para o Dock).

No menu: Sincronizar agora · Re-sincronizar · Apagar blocos ·
Abrir configuração · Ver log · Iniciar no login.

Se o install.sh já tinha registrado o LaunchAgent, o menu oferece
"Desativar agendador antigo". Os dois coexistem sem conflito — usam
a mesma trava — mas com o app aberto o LaunchAgent é redundante.
================================================================
EOF
