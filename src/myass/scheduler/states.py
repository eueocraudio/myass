"""Estados da atividade e respostas do protocolo de despacho.

A máquina de estados (ver *Máquina de estados da atividade* em ``CLAUDE.md``):

    ENFILEIRADA --dispatch--> EXECUTANDO --RESULT ok------> CONCLUIDA
                                 |  ^                         (tick avança o cursor)
                                 |  | beat renova
                                 |  +-- lease vencido & tentativa<max --> ENFILEIRADA
                                 |
                                 +-- RESULT erro_logico ---> FALHA_LOGICA (motivo=erro_logico)
                                 +-- timeout_total estourou -> FALHA_LOGICA (motivo=timeout)
                                 +-- lease vencido & tentativa=max -> FALHA_LOGICA (motivo=esgotada)

``CONCLUIDA`` e ``FALHA_LOGICA`` são terminais. ``ESGOTADA`` da figura é o
*ponto de conversão* entre as duas camadas de falha: uma falha de infra crônica
(lease vencido ``max_tentativas`` vezes) é **promovida** a falha lógica
(``FALHA_LOGICA`` com ``motivo="esgotada"``) e segue para a cadeia de catch.
"""

# Estados de uma atividade despachada.
ENFILEIRADA = "enfileirada"     # na fila, aguardando (re)despacho
EXECUTANDO = "executando"       # entregue a um block, lease ativo
CONCLUIDA = "concluida"         # RESULT ok (terminal)
FALHA_LOGICA = "falha_logica"   # erro lógico / timeout / esgotada (terminal)

TERMINAIS = frozenset({CONCLUIDA, FALHA_LOGICA})

# Motivos de FALHA_LOGICA.
MOTIVO_ERRO_LOGICO = "erro_logico"   # o script retornou exit != 0
MOTIVO_TIMEOUT = "timeout"           # timeout_total estourou (script pendurado)
MOTIVO_ESGOTADA = "esgotada"         # max_tentativas de lease vencido

# Status que um RESULT pode carregar.
RESULT_OK = "ok"
RESULT_ERRO_LOGICO = "erro_logico"

# Respostas do Scheduler ao Executor (camada de aplicação).
BEAT_ACK = "BEAT_ACK"
WORK_CANCEL = "WORK_CANCEL"
RESULT_ACK = "RESULT_ACK"
RELEASE_ACK = "RELEASE_ACK"
