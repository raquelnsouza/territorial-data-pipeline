# Roteiro do vídeo de demonstração (3 a 4 minutos)

Grave a tela (OBS ou o gravador do Windows). Fale devagar e mostre, não explique demais.

1. **(20 s) O problema.** "Bases públicas mudam; atualizar na mão dá erro e consome tempo. Aqui, uma rotina que atualiza sozinha, valida e deixa rastro."
2. **(40 s) O fluxo.** Airflow → DAG `territorial_update` → grafo das 6 tarefas. Explique em uma frase cada etapa.
3. **(40 s) Falha controlada.** Dispare com `forcar_falha_validacao`. Mostre a tarefa vermelha, o log com a regra que bloqueou e o e-mail/registro de alerta. Diga: "o dado anterior continua intacto".
4. **(40 s) Sucesso.** Dispare normal. Mostre as tarefas verdes e abra `/relatorio/`: mapa e tabela de validações.
5. **(30 s) Rastreabilidade.** Mostre a tabela `audit.atualizacoes` (data, fonte, checksum, linhas) no DBeaver/QGIS ou no relatório.
6. **(20 s) Sem mudança.** Rode de novo: tarefas puladas. "Só recarrega quando a fonte muda."
7. **(20 s) Fechamento.** README, testes e como incluir uma base nova. Diga que o mesmo desenho serve para qualquer base pública (SICAR, SIGEF, PRODES…).

Dica: deixe o terminal/abas limpos e use zoom de 125% no navegador para ficar legível.
