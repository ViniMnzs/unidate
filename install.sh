#!/bin/bash
# ---------------------------------------------------------------------------
# unidate — instalador
# Instala o sincronizador de agendas "Ocupado" em ~/.unidate
# e registra um LaunchAgent que roda a cada 15 minutos.
# ---------------------------------------------------------------------------
set -uo pipefail

DIR="$HOME/.unidate"
LABEL="br.com.mnzs.unidate"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Este instalador só roda no macOS." >&2
  exit 1
fi

mkdir -p "$DIR/lib" "$DIR/logs"

# ---------------------------------------------------------------------------
# Descoberta de interpretadores Python
# /usr/bin/python3 vem primeiro: é assinado pela Apple e dá o comportamento
# mais estável nas permissões de Calendário (TCC), inclusive sob launchd.
# ---------------------------------------------------------------------------
CANDIDATES=(/usr/bin/python3)
for p in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
         /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 \
         /usr/local/bin/python3.13 /usr/local/bin/python3.12 \
         /usr/local/bin/python3.11 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.11/bin/python3; do
  [[ -x "$p" ]] && CANDIDATES+=("$p")
done
if command -v python3 >/dev/null 2>&1; then
  CANDIDATES+=("$(command -v python3)")
fi

# remove duplicados preservando a ordem
UNIQ=()
for p in "${CANDIDATES[@]}"; do
  dup=0
  for q in ${UNIQ[@]+"${UNIQ[@]}"}; do [[ "$p" == "$q" ]] && dup=1 && break; done
  [[ $dup -eq 0 ]] && UNIQ+=("$p")
done

pip_flag_supported() {   # $1 = python, $2 = flag
  "$1" -m pip install --help 2>/dev/null | grep -q -- "$2"
}

# Um "user = true" no pip.conf (ou PIP_USER no ambiente) quebra o --target com
# "Can not combine '--user' and '--target'". PIP_USER=0 neutraliza isso sem
# descartar o resto da configuração (índice interno, proxy etc.).
report_pip_config() {
  local found=0 f
  for f in "$HOME/.config/pip/pip.conf" "$HOME/.pip/pip.conf" \
           "/Library/Application Support/pip/pip.conf" "/etc/pip.conf" \
           "${PIP_CONFIG_FILE:-}"; do
    [[ -n "$f" && -f "$f" ]] || continue
    if grep -Eq '^[[:space:]]*user[[:space:]]*=[[:space:]]*(true|yes|1)' "$f"; then
      echo "    Aviso: '$f' força instalação --user; ignorando via PIP_USER=0."
      found=1
    fi
  done
  if [[ "${PIP_USER:-}" =~ ^(1|true|yes|True)$ ]]; then
    echo "    Aviso: variável PIP_USER=$PIP_USER no ambiente; ignorando."
    found=1
  fi
  return $found
}

try_python() {
  local py="$1"
  local ver minor spec extra=()

  ver="$("$py" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)" || return 1
  minor="${ver#*.}"
  [[ "${ver%%.*}" == "3" ]] || return 1
  if (( minor < 9 )); then
    echo "    $py ($ver) — muito antigo para o PyObjC, pulando."
    return 1
  fi

  # pyobjc 12.x exige Python >= 3.10; no 3.9 a última série compatível é a 11.1
  if (( minor == 9 )); then
    spec="pyobjc-framework-EventKit==11.1"
  else
    spec="pyobjc-framework-EventKit"
  fi

  echo "--> Tentando $py (Python $ver) com $spec"

  if ! "$py" -m pip --version >/dev/null 2>&1; then
    echo "    pip ausente; tentando ensurepip"
    "$py" -m ensurepip --default-pip >/dev/null 2>&1 || {
      echo "    sem pip disponível, pulando."; return 1; }
  fi

  pip_flag_supported "$py" "--break-system-packages" && extra+=(--break-system-packages)

  rm -rf "$DIR/lib"
  mkdir -p "$DIR/lib"

  if ! env PIP_USER=0 "$py" -m pip install --disable-pip-version-check --no-input \
        --no-cache-dir --target "$DIR/lib" ${extra[@]+"${extra[@]}"} "$spec"; then
    echo "    Primeira tentativa falhou; repetindo sem ler nenhum pip.conf."
    rm -rf "$DIR/lib"; mkdir -p "$DIR/lib"
    if ! env PIP_CONFIG_FILE=/dev/null PIP_USER=0 "$py" -m pip install \
          --disable-pip-version-check --no-input --no-cache-dir \
          --target "$DIR/lib" ${extra[@]+"${extra[@]}"} "$spec"; then
      echo "    Instalação do PyObjC falhou com $py."
      return 1
    fi
  fi

  if PYTHONPATH="$DIR/lib" "$py" -c 'import EventKit, Foundation' 2>/dev/null; then
    echo "    OK — EventKit importado com sucesso."
    PY="$py"
    return 0
  fi

  echo "    PyObjC instalou mas não importou com $py."
  return 1
}

echo "==> Verificando a configuração do pip"
report_pip_config || true

echo "==> Procurando um Python com suporte a EventKit"
PY=""
for cand in "${UNIQ[@]}"; do
  if try_python "$cand"; then break; fi
done

if [[ -z "$PY" ]]; then
  cat >&2 <<'EOM'

Não consegui instalar o PyObjC/EventKit com nenhum Python encontrado.

Saída completa dos erros está acima. Caminhos comuns de solução:

  1. Instalar as Command Line Tools:
         xcode-select --install

  2. Instalar um Python mais novo (recomendado: 3.11+):
         brew install python@3.12
     e rodar ./install.sh de novo.

  3. Testar manualmente para ver o erro isolado:
         /usr/bin/python3 -m pip install --target /tmp/eklib \
             "pyobjc-framework-EventKit==11.1"

EOM
  exit 1
fi

echo "==> Usando $PY ($("$PY" -V 2>&1))"

echo "==> Copiando arquivos"
cp "$SRC/unidate.py" "$DIR/unidate.py"
[[ -f "$SRC/uninstall.sh" ]] && cp "$SRC/uninstall.sh" "$DIR/uninstall.sh"
chmod +x "$DIR/unidate.py" 2>/dev/null || true
chmod +x "$DIR/uninstall.sh" 2>/dev/null || true
printf '%s' "$PY" > "$DIR/python_path"

cat > "$DIR/run.sh" <<'EOS'
#!/bin/bash
DIR="$HOME/.unidate"
export PYTHONPATH="$DIR/lib"
PY="$(cat "$DIR/python_path")"
LOG="$DIR/logs/unidate.log"
if [[ -f "$LOG" ]] && [[ $(wc -c < "$LOG") -gt 2000000 ]]; then
  mv "$LOG" "$LOG.1"
fi
if [[ $# -eq 0 ]]; then set -- sync; fi
exec "$PY" "$DIR/unidate.py" "$@" >> "$LOG" 2>&1
EOS
chmod +x "$DIR/run.sh"

echo "==> Gerando configuração (o macOS vai pedir acesso ao Calendário agora)"
export PYTHONPATH="$DIR/lib"
if [[ -f "$DIR/config.json" ]]; then
  echo "    config.json já existe — preservado."
  "$PY" "$DIR/unidate.py" calendars || exit 1
else
  "$PY" "$DIR/unidate.py" init || exit 1
fi

echo "==> Instalando o LaunchAgent (a cada 15 minutos)"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOP
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$DIR/run.sh</string>
        <string>sync</string>
    </array>
    <key>StartInterval</key>
    <integer>900</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>ProcessType</key>
    <string>Background</string>
    <key>StandardOutPath</key>
    <string>$DIR/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/logs/launchd.err.log</string>
</dict>
</plist>
EOP

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"

cat <<EOF

================================================================
Instalado com $PY

1) Revise quais agendas participam:
     open -e $DIR/config.json

2) Teste sem alterar nada:
     $DIR/run.sh sync --dry-run ; tail -40 $DIR/logs/unidate.log

3) A rotina já roda sozinha a cada 15 min. Para forçar agora:
     launchctl kickstart -k gui/$(id -u)/$LABEL

Log:          $DIR/logs/unidate.log
Desinstalar:  $DIR/uninstall.sh
================================================================
EOF
