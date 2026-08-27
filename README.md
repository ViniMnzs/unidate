# unidate

**Suas várias agendas param de marcar reunião uma em cima da outra.**

O unidate é um aplicativo para macOS que vive na barra de menus. Ele olha os seus compromissos em todas as suas contas de calendário e cria blocos genéricos chamados **"Ocupado"** nas agendas que estavam livres naquele horário.

Nada sai do seu Mac. Nenhum link compartilhado, nenhum servidor, nenhuma conta a criar.

---

## O problema

Você tem calendário do trabalho, calendário pessoal, talvez um de um cliente. Cada um numa conta diferente.

Quinta-feira, 14h: você tem dentista, marcado na agenda pessoal.

Seu colega abre a agenda do trabalho, vê "livre" às 14h de quinta, e marca uma reunião. Ele não fez nada errado — a agenda dele **realmente** mostrava livre.

Compartilhar as agendas entre si resolveria, mas quase nunca é possível: contas corporativas costumam proibir compartilhamento com domínios externos. E você provavelmente não quer que o trabalho veja "Dentista — Dra. Fulana" mesmo que pudesse.

## A solução

O unidate cria, na agenda do trabalho, um bloco assim:

```
Quinta, 14:00 – 15:00
Ocupado
```

É isso. Só isso. Seu colega vê que você está ocupado e não marca em cima.

### Antes e depois

```
ANTES                                       DEPOIS

Agenda pessoal   Agenda do trabalho         Agenda pessoal   Agenda do trabalho
14h Dentista     14h  (livre)               14h Dentista     14h Ocupado
    (livre)      16h Reunião de equipe      16h Ocupado      16h Reunião de equipe
```

As duas agendas passam a se proteger. Funciona com quantas contas você tiver.

## O que ele **não** faz

Este é o ponto mais importante, então está em seção própria:

| Nunca é copiado | |
|---|---|
| Título do compromisso | o bloco se chama só "Ocupado" |
| Participantes | ninguém descobre com quem você fala |
| Local | nem endereço, nem sala |
| Link da reunião | nada de Zoom/Meet vazando |
| Notas e anexos | nada |

A única informação que atravessa é *"existe um compromisso das 14h às 15h"*.

E não existe nuvem no meio: o unidate conversa direto com o app Calendário do seu Mac. Seus dados não passam por nenhum servidor nosso, porque não existe servidor nosso.

---

## Instalação

Você precisa de um Mac com **macOS 11 (Big Sur) ou mais novo**.

### Caminho fácil: baixar pronto

1. Vá em **[Releases](https://github.com/ViniMnzs/unidate/releases)** e baixe o arquivo da versão mais recente. **Há dois, escolha pelo processador do seu Mac:**

   | Seu Mac | Baixe |
   |---|---|
   | Chip Apple (M1, M2, M3, M4…) | `unidate-arm64.zip` |
   | Processador Intel | `unidate-x86_64.zip` |

   Não sabe qual é o seu? Menu  no alto à esquerda → **Sobre este Mac**. Se aparecer "Chip Apple M…", é o primeiro. Se aparecer "Processador Intel", é o segundo.

2. Descompacte (dois cliques).
3. Arraste o **unidate.app** para a pasta **Aplicativos**.
4. **Na primeira vez:** clique com o **botão direito** no unidate e escolha **Abrir**. Vai aparecer um aviso dizendo que o desenvolvedor não pôde ser verificado — clique em **Abrir** de novo.

> **Por que esse aviso aparece?** Publicar um app sem ele exige uma conta paga de desenvolvedor Apple (US$ 99 por ano), e este projeto não tem. O aviso não indica que há algo errado com o app — indica que ninguém pagou à Apple para revisá-lo. Você só passa por isso na primeira abertura.

Se preferir tirar o aviso pelo Terminal, uma linha resolve:

```bash
xattr -d com.apple.quarantine /Applications/unidate.app
```

### Caminho do desenvolvedor: compilar você mesmo

Se você prefere não baixar binário de ninguém:

```bash
git clone https://github.com/ViniMnzs/unidate.git
cd unidate
./build_app.sh --install
```

O script cria um ambiente Python isolado dentro da pasta do projeto, baixa o que precisa **só ali dentro** (não mexe no Python do seu sistema), monta o app e instala em `/Aplicativos`. Compilado na sua máquina, o aviso do Gatekeeper não aparece.

---

## Primeiro uso

### 1. Autorize o acesso ao Calendário

Na primeira abertura o macOS pergunta se o unidate pode acessar seu Calendário. **Permita.** Sem isso ele não faz nada — e é a única permissão que ele pede.

Se você clicou em "Não permitir" por engano: **Ajustes do Sistema → Privacidade e Segurança → Calendários** → ligue o unidate.

### 2. Encontre o ícone

O unidate **não aparece no Dock**. Ele vive na barra de menus, no alto à direita da tela, como um ícone de calendário com um relógio.

Se sua barra de menus estiver cheia e o ícone não couber, apps como o [Ice](https://github.com/jordanbaird/Ice) ajudam a organizar.

### 3. Escolha as agendas

Clique no ícone. Você vai ver dois submenus:

- **Ler compromissos de…** — de quais agendas o unidate deve olhar seus compromissos.
- **Criar blocos "Ocupado" em…** — em quais agendas ele deve criar os blocos.

Cada um lista as agendas que existem no seu Mac, **agrupadas por conta**, com o nome que você já conhece. Basta marcar e desmarcar. Você nunca precisa descobrir código, ID ou número de nada.

Na primeira vez o unidate já vem com uma escolha razoável. Ele **liga** as agendas de contas conectadas (Google, Microsoft/Exchange, iCloud) e deixa **de fora**:

| Fica de fora por padrão | Por quê |
|---|---|
| **Feriados** e **Aniversários** | Não são compromissos, e como são eventos de dia inteiro, deixariam o dia todo marcado como ocupado em todas as suas agendas. Um feriado nacional não significa que você está ocupado |
| A agenda local **"Meu Mac"** | Não é conta conectada; nada ali precisa ser espelhado para fora |
| Agendas **assinadas** | Calendários públicos que você só acompanha |
| Agendas **somente leitura** | Não podem receber blocos. Continuam podendo ser origem |

Se estiver bom, não precisa mexer. E se você quiser uma dessas na sincronização, basta marcar no menu — a escolha que você faz à mão nunca é desfeita depois.

> **Sobre feriados e aniversários:** o Google e o Microsoft entregam essas agendas como agendas comuns, não com um tipo especial que dê para filtrar. O unidate as reconhece pelo nome, por trecho, porque o nome vem com o país colado — `Feriados de Brasil`, `Holidays in Brazil`, `Feiertage in Deutschland`. Funciona em seis idiomas.

> **Os dois submenus são independentes de propósito.** Uma agenda corporativa que não permite escrita pode ficar marcada só em "Ler compromissos de…" — ela protege as outras sem receber nada. Agendas somente-leitura aparecem desmarcáveis e rotuladas.

### 4. Pronto

O unidate sincroniza a cada 15 minutos, sozinho. Se quiser ver acontecer agora, clique em **Sincronizar agora**.

Para ele abrir junto com o Mac, marque **Iniciar no login**.

---

## Uso no dia a dia

Normalmente: nenhum. Ele trabalha em silêncio.

Quando você clicar no ícone, vai encontrar:

| Item do menu | Para que serve |
|---|---|
| *primeira linha* | O que aconteceu no último ciclo |
| *segunda linha* | De quanto em quanto tempo ele roda e quantas agendas estão ligadas |
| **Sincronizar agora** | Não quer esperar os 15 minutos |
| **Re-sincronizar** | Desconfiou que algo ficou estranho: apaga todos os blocos e reconstrói do zero |
| **Apagar todos os blocos** | Limpar tudo que o unidate criou, sem desinstalar |
| **Ler compromissos de…** | Escolhe as agendas de origem |
| **Criar blocos "Ocupado" em…** | Escolhe as agendas de destino |
| **Ajustes** | Submenu com os interruptores mais usados, sem abrir arquivo nenhum: incluir eventos de dia inteiro, ignorar eventos marcados como "Livre", ignorar convites recusados |
| **Abrir configuração** | Abre o arquivo de ajustes (veja abaixo) |
| **Ver log** | Abre o registro do que ele fez, útil se algo parecer errado |
| **Recriar configuração** | Redetecta suas agendas do zero |
| **Iniciar no login** | Abrir junto com o Mac |
| **Sair do unidate** | Encerra. Ele para de sincronizar até você abrir de novo |

Desmarcar uma agenda em "Criar blocos em…" **pergunta antes** e apaga os blocos que o unidate havia criado lá. Seus compromissos nunca são tocados.

---

## Ajustes

Quase ninguém precisa mexer aqui. Se quiser, o menu **Abrir configuração** abre um arquivo de texto com estas opções:

| Ajuste | O que faz | Padrão |
|---|---|---|
| `dias_a_frente` | Até quantos dias no futuro ele cria blocos | 60 |
| `intervalo_minutos` | De quanto em quanto tempo sincroniza. Mínimo 5 | 15 |
| `duracao_minima_bloco_min` | Duração mínima de cada bloco. Um convite de 15 min (10h–10h15) vira um bloco de 30 min (10h–10h30), para ninguém encaixar reunião no resto da meia hora | 30 |
| `duracao_minima_min` | Ignora compromissos mais curtos que isto. Suba para 15 se reuniões curtíssimas poluem | 0 |
| `incluir_dia_inteiro` | Se compromissos de dia inteiro devem virar bloco. **Desligado por padrão**, e é o que você quer na maioria dos casos: férias, feriados, aniversários e lembretes de dia inteiro deixariam o dia todo marcado como ocupado em todas as suas agendas. Também disponível no menu **Ajustes** | não |
| `ignorar_eventos_livres` | Pula o que você marcou como "Livre/Disponível" | sim |
| `ignorar_recusados` | Pula convites que você recusou | sim |
| `titulo_espelho` | O nome dos blocos. Pode trocar por "Indisponível", por exemplo | Ocupado |
| `politica_sobreposicao` | Quando **não** criar bloco porque o destino já estava ocupado. `cobertura_total` só pula se ele já estiver ocupado durante todo o intervalo; `qualquer_sobreposicao` pula com qualquer encavalamento; `nunca` sempre cria | cobertura_total |
| `max_mudancas_por_ciclo` | Teto de alterações por ciclo. Existe porque Google e Microsoft rejeitam escrita em massa e chegam a marcar erro na conta. O excedente sai no ciclo seguinte | 100 |

Depois de editar, salve. O unidate aplica no ciclo seguinte, sem reiniciar.

**Chave que não está no arquivo usa o padrão.** Para mudar uma que não aparece, basta adicionar a linha.

---

## Perguntas frequentes

**Ele altera ou apaga meus compromissos?**
Não. Toda remoção exige uma assinatura invisível que o próprio unidate grava nas notas do bloco. Existe uma exceção precisa: se sobrarem **dois ou mais** blocos "Ocupado" no mesmo minuto na mesma agenda, ele mantém um e apaga os repetidos. Um bloco "Ocupado" solitário que você criou à mão nunca é tocado.

**Preciso deixar o Mac ligado?**
Sim, e o app aberto. Ele não roda na nuvem. Quando o Mac acorda, sincroniza no próximo ciclo.

**Funciona com Google, Microsoft, iCloud?**
Com qualquer conta que apareça no app **Calendário** do macOS. Se está lá, o unidate a vê. Contas que só existem dentro do app Outlook não aparecem — adicione em Calendário → Ajustes → Contas.

**Meu celular também vai mostrar os blocos?**
Sim, assim que a conta sincronizar normalmente (alguns minutos). Os blocos são eventos comuns na sua conta.

**E se eu remarcar ou cancelar um compromisso?**
O bloco correspondente acompanha no ciclo seguinte: muda de horário junto, ou desaparece.

**Os blocos vão me notificar?**
Não. São criados sem nenhum alarme, e se o servidor da conta inserir um alarme padrão, o ciclo seguinte o remove.

**Uma agenda minha é somente-leitura. E aí?**
Ela pode continuar como origem — protege as outras — mas não recebe blocos. O unidate detecta isso sozinho e a mostra desmarcável na lista de destino.

**Posso usar em várias máquinas?**
Sim, mas instale em uma só por conta. Duas instalações escrevendo nas mesmas agendas fazem trabalho duplicado.

---

## Se algo der errado

**Não vejo o ícone na barra de menus.**
O app não vai para o Dock. Verifique se está aberto (⌘Espaço → "unidate"). Se a barra estiver cheia, o ícone pode não ter caído na tela.

**"acesso ao Calendário negado"**
Ajustes do Sistema → Privacidade e Segurança → Calendários → ligue o unidate. Se já estiver ligado e continuar falhando, desligue e ligue de novo.

**Blocos "Ocupado" repetidos no mesmo horário.**
Ele limpa sozinho no próximo ciclo. Para resolver na hora, clique em **Re-sincronizar**.

**Blocos demais, poluindo a agenda.**
Três caminhos: suba `duracao_minima_min` para 15, reduza `dias_a_frente`, ou mude `politica_sobreposicao` para `qualquer_sobreposicao`.

**Uma conta aparece com triângulo de erro no app Calendário.**
Esse é um problema entre o Calendar.app e o servidor da sua conta, não do unidate. Clique no triângulo para ver a mensagem. Uma causa comum é volume: se você acabou de instalar e ele criou centenas de blocos, o servidor pode reclamar temporariamente — daí o teto de `max_mudancas_por_ciclo`.

**Uma conta não aparece na lista de agendas.**
Ela não está no app Calendário. Adicione em Calendário → Ajustes → Contas.

**Quero ver o que ele andou fazendo.**
Menu → **Ver log**.

---

## Desinstalar

1. Ícone → **Apagar todos os blocos** (remove o que ele criou nas suas agendas).
2. Ícone → **Sair do unidate**.
3. Arraste o **unidate.app** da pasta Aplicativos para o Lixo.
4. Opcional, para não deixar rastro de configuração:

```bash
rm -rf ~/.unidate ~/Library/LaunchAgents/br.com.mnzs.unidate.app.plist
```

Seus compromissos originais ficam intactos.

---

# Para desenvolvedores

O que segue não é necessário para usar o app.

## Estrutura

```
unidate.py             toda a lógica de sincronização e a CLI
app/unidate_app.py     interface: menu, timer, alertas — nenhuma lógica de sync
app/setup.py           receita do py2app (Info.plist, chaves de permissão)
build_app.sh           monta e instala dist/unidate.app
install.sh             instalação alternativa por linha de comando (LaunchAgent)
uninstall.sh           remove agendador, blocos e pasta
tests/test_unidate.py  suíte completa
tests/stub/            EventKit e Foundation falsos, para rodar fora do macOS
```

**Nenhuma decisão sobre o que espelhar vive em `app/`.** O app só chama `cmd_sync`, `cmd_resync`, `cmd_purge`, `cmd_init`, `listar_agendas` e `definir_papel`. A interface não pode ser testada sem GUI, então tudo que decide comportamento fica em `unidate.py`, onde a suíte alcança.

## Testes

Rodam **fora do macOS** e sem permissão de Calendário: `tests/stub/` traz um EventKit falso no lugar do framework do sistema. A lógica testada é a real — os comandos são chamados do início ao fim, lendo e gravando arquivos de verdade num diretório temporário.

```bash
python3 tests/test_unidate.py    # imprime OK/FALHA por cenário
echo $?                          # 0 = tudo passou
```

## Como ele evita duplicação

Três defesas **independentes**, para que nenhuma sozinha seja ponto único de falha:

- **Assinatura.** Cada bloco carrega uma marca invisível nas notas (`[unidate/v1] src=…`). O projeto se chamava *calsync*; blocos antigos trazem `[calsync/v1]` e continuam reconhecidos — escreve o formato novo, lê os dois. Blocos fora da janela de sincronização nunca são reescritos, e sem a leitura dupla ficariam invisíveis até para o comando de limpeza.
- **Título.** Um evento chamado "Ocupado" nunca é usado como origem, com ou sem assinatura. Isso importa porque Exchange e Google **podem descartar o campo de notas** no caminho de volta: sem essa defesa, um bloco que perdeu a assinatura viraria "compromisso" aos olhos do programa e geraria uma cascata de cópias a cada ciclo.
- **Unicidade por horário.** Numa mesma agenda não pode existir mais de um "Ocupado" com o mesmo minuto de início e fim. O excedente é removido, preservando o que tem assinatura válida.

Somado a isso:

- **Idempotente.** Um ciclo sem novidade registra `Criados: 0 | Atualizados: 0 | Removidos: 0`.
- **Identidade estável da origem.** A chave da assinatura vem de `calendarItemExternalIdentifier`, não de `eventIdentifier` — este último é reemitido por Exchange/CalDAV entre instâncias do store, o que fazia todos os blocos serem apagados e recriados a cada ciclo.
- **Autocura.** Bloco que perdeu a assinatura no servidor é re-estampado e volta a ser gerenciável.
- **Uma execução por vez.** Trava exclusiva `flock` em `~/.unidate/unidate.lock`.
- **Teto por ciclo.** Rajada de escrita faz servidores rejeitarem em massa; o excedente espera o ciclo seguinte.
- **Agenda desligada é limpa,** inclusive fora da janela de `dias_a_frente`.
- **Conta readicionada é religada sozinha.** Trocar uma conta muda o identificador da agenda; o unidate reconhece pelo par (nome, conta) quando há um único candidato, e **avisa em vez de adivinhar** quando há ambiguidade.
- **Recorrências** são tratadas ocorrência a ocorrência.

## CLI

O app é a forma recomendada, mas toda a lógica também roda por linha de comando. Com a instalação alternativa via `./install.sh`, `~/.unidate/run.sh` embrulha tudo:

```bash
R=~/.unidate/run.sh

$R calendars                                  # lista as agendas visíveis
$R init                                       # cria a configuração
$R init --force                               # recria do zero
$R sync --dry-run                             # simula, não altera nada
$R sync                                       # sincroniza agora
$R status                                     # quantos blocos por agenda
$R purge                                      # conta o que seria apagado
$R purge --yes                                # apaga os blocos assinados
$R purge --yes --incluir-sem-assinatura       # apaga também os sem assinatura
$R resync --yes                               # apaga tudo e reconstrói
```

`--incluir-sem-assinatura` é destrutivo: o filtro é só o título, então um evento **seu** chamado "Ocupado" também casaria. Confira antes com `$R purge --incluir-sem-assinatura` (sem o `--yes`).

Rótulos do log em `--dry-run`:

| Linha | Significa |
|---|---|
| `CRIAR` | bloco novo |
| `ATUALIZAR` | horário, título, assinatura ou alarme fora do esperado |
| `REMOVER (dup)` | já existe outro no mesmo minuto |
| `REMOVER (órfão)` | assinado, mas a origem não existe mais |
| `REMOVER (fora-jan)` | fora da janela, localizado pelo estado gravado |
| `REMOVER (deslig.)` | agenda que deixou de participar |
| `FALHA` | o macOS recusou a operação |

## Empacotamento

```bash
./build_app.sh            # gera dist/unidate.app
./build_app.sh --install  # gera e instala em /Applications
```

Antes de empacotar, o script roda duas portas de qualidade, porque um `.app` que compila pode ainda assim abrir e morrer:

1. **importa o módulo do app** — é isso que dispara a transformação de classe do PyObjC, onde erros de prototipagem de selector aparecem;
2. **confere o `Info.plist`** — `LSUIElement` e as duas chaves de uso de Calendário. Sem elas o macOS mata o app no instante em que ele pede permissão.

Log completo do py2app em `build/py2app.log`.

## Publicando uma release

As releases são montadas pelo GitHub Actions, não na máquina de ninguém. Enviar uma tag basta:

```bash
git tag -a v1.0.0 -m "unidate 1.0.0"
git push origin v1.0.0
```

O workflow em `.github/workflows/release.yml` então:

1. roda a suíte de testes (ela não precisa de macOS nem de permissão de Calendário, então serve de porta antes de gastar tempo empacotando);
2. monta o app **em dois runners** — `macos-14` (arm64) e `macos-13` (Intel) — porque o py2app empacota para a arquitetura em que roda, e um bundle arm64 não abre em Mac Intel;
3. empacota cada um com `ditto` (o `zip` comum quebra bundles: perde symlinks e resource forks);
4. cria a release com os dois `.zip` anexados, usando o `gh` que já vem nos runners — sem depender de action de terceiro.

Para refazer uma release, apague a tag e a release e envie a tag de novo:

```bash
gh release delete v1.0.0 --yes
git push --delete origin v1.0.0
```

## Licença

MIT. Veja [LICENSE](LICENSE).
