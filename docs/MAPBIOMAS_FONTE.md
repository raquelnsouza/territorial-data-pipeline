# Fonte do MapBiomas (arquivo grande no Google Drive)

O pipeline lê a **tabela de estatísticas de cobertura e uso da terra por município** do MapBiomas
(`.xlsx` com uma coluna por ano, em hectares). O arquivo fica no **Google Drive** e o Airflow baixa
direto de lá, **a cada execução** — não é preciso copiar nada para o servidor.

## Configurar (uma vez)
1. No Drive, clique com o botão direito no arquivo → **Compartilhar** → *Acesso geral* →
   **Qualquer pessoa com o link** (permissão *Leitor*). Sem isso o servidor não consegue baixar.
2. Copie o link e cole em `MAPBIOMAS_URL` no `.env`. Qualquer um destes formatos funciona:
   * `https://drive.google.com/uc?id=SEU_ID&export=download`
   * `https://drive.google.com/file/d/SEU_ID/view?usp=sharing`
   * `https://drive.google.com/open?id=SEU_ID`
3. Subiu uma coleção nova do MapBiomas? **Substitua o conteúdo do arquivo no Drive** (opção
   *Gerenciar versões*, que mantém o mesmo link) ou troque o link. Na próxima execução o pipeline vê
   que o checksum mudou e recarrega sozinho.

## Como o pipeline lida com arquivo grande
| Problema | Solução |
|---|---|
| O Drive mostra a página "não foi possível verificar vírus" em vez do arquivo | O pipeline segue o formulário de confirmação automaticamente |
| Download cortado no meio | O arquivo só é aceito se chegar inteiro (grava em `.part` e confere o tamanho) |
| Salvar uma página de erro como se fosse o `.xlsx` | Confere a assinatura do arquivo e falha com mensagem clara |
| Planilha enorme estourando a memória | Leitura em *streaming*: só as linhas do estado ficam na memória (teste: ~115 MB de RAM) |
| Disco enchendo com um arquivo grande por semana | Se a fonte não mudou, a cópia é apagada; guarda só as 3 últimas versões (`TERRITORIAL_RAW_RETENCAO`) |
| Tarefa travada | Limite de 60 minutos na tarefa de download, com 2 novas tentativas |

O registro (data, link, tamanho, checksum) de cada download continua na tabela `audit.atualizacoes`,
mesmo quando a cópia do arquivo é apagada.

## Mensagens de erro e o que fazer
* **"pediu login"** → o compartilhamento não está como *Qualquer pessoa com o link*.
* **"excesso de acessos (cota diária)"** → o Drive limita downloads de arquivos muito acessados.
  Espere algumas horas ou faça uma cópia do arquivo (*Fazer uma cópia*) e use o link da cópia.
  Com execução semanal isso não costuma acontecer.
* **"não é um .xlsx válido"** → o link não aponta para o arquivo (ou aponta para uma pasta).

## O que o pipeline espera dentro do arquivo
| Item | Esperado | Onde mudar se a coleção mudar |
|---|---|---|
| Aba | `COVERAGE_11` (ou a 1ª aba que começa com `COVERAGE`) | `MAPBIOMAS_ABA` |
| Código do município | coluna `geocode` (aceita também `cd_mun`, `cod_municipio`) | `config.py` |
| Classe | coluna `class_id` | `config.py` |
| Anos | colunas com nome de 4 dígitos (`1985` … `2024`) | automático |

Se o formato mudar, a execução **falha dizendo qual coluna não foi encontrada** (e quais existem),
em vez de carregar dado errado.

## Para produção (ideia de evolução)
Hoje a detecção de mudança baixa o arquivo inteiro e compara o checksum. Em produção dá para consultar
só a data de modificação pela API do Drive (ou pelo próprio MapBiomas) e baixar apenas quando mudar.
`MAPBIOMAS_ARQUIVO_LOCAL` continua existindo, mas só como alternativa para testes offline.

## Conferir na primeira execução real
Os testes automáticos usam dados sintéticos no mesmo formato. Na primeira execução com o arquivo real,
olhe a tabela "Validações" em `/relatorio/`: `cobertura.join_com_ibge` e
`cobertura.area_consistente_com_ibge` mostram na hora se códigos e áreas batem com o IBGE.
