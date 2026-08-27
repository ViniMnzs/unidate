#!/bin/bash
# unidate — desinstalador. Remove os blocos "Ocupado" criados, o agendamento
# e a pasta de instalação. Nenhum compromisso seu é tocado.
set -uo pipefail

DIR="$HOME/.unidate"
LABEL="br.com.mnzs.unidate"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "==> Parando o agendamento"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"

if [[ -f "$DIR/unidate.py" && -f "$DIR/python_path" ]]; then
  echo "==> Removendo os blocos Ocupado criados pelo unidate"
  export PYTHONPATH="$DIR/lib"
  PY="$(cat "$DIR/python_path")"
  "$PY" "$DIR/unidate.py" purge --yes || \
    echo "    (não foi possível remover automaticamente — rode 'purge --yes' manualmente)"

  # Blocos cuja assinatura foi descartada pelo servidor sobrevivem ao purge acima.
  # Removê-los exige confirmação: o filtro é por título, e um evento SEU chamado
  # "Ocupado" casaria do mesmo jeito.
  pend="$("$PY" "$DIR/unidate.py" purge --incluir-sem-assinatura 2>/dev/null || true)"
  if [[ "$pend" == *"seriam removidos"* ]]; then
    echo "    $pend"
    read -r -p "    Remover também esses blocos sem assinatura? Um evento SEU chamado \"Ocupado\" também seria apagado. [s/N] " ans2
    if [[ "${ans2:-N}" =~ ^[sSyY]$ ]]; then
      "$PY" "$DIR/unidate.py" purge --yes --incluir-sem-assinatura || true
    fi
  fi
fi

read -r -p "Apagar a pasta $DIR? [s/N] " ans
if [[ "${ans:-N}" =~ ^[sSyY]$ ]]; then
  rm -rf "$DIR"
  echo "Pasta removida."
else
  echo "Pasta preservada em $DIR"
fi
echo "Pronto."
