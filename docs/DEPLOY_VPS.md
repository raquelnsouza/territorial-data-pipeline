# Colocar online numa VPS

## Caminho rápido (a partir do Windows)
Na pasta do projeto, no PowerShell (a chave SSH já configurada na sua máquina é usada normalmente):

Primeiro um diagnóstico **somente leitura** (portas em uso, Docker, memória, disco — não altera nada):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -Servidor 187.102.244.199 -Chave "$env:USERPROFILE\.ssh\radar_vps" -Diagnostico
```

Se estiver tudo bem (portas 80 e 443 livres, RAM suficiente), o deploy:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -Servidor 187.102.244.199 -Chave "$env:USERPROFILE\.ssh\radar_vps" -MapbiomasUrl "https://drive.google.com/uc?id=SEU_ID&export=download"
```

O script envia o projeto, instala o Docker se faltar, gera senhas e chaves aleatórias, sobe tudo (se as portas 80/443 já estiverem ocupadas por outro serviço, ele **para sem mexer em nada**) e
**mostra no final** os endereços, os usuários e as senhas (guarde-as; ficam também em `/opt/territorial-data-pipeline/.env`).

Requisitos da VPS: Ubuntu 22.04/24.04, **pelo menos 4 GB de RAM** (2 GB trava o Airflow), 2 vCPU, 40 GB de disco.

### Endereço e HTTPS
* Com domínio: `-Dominio demo.seudominio.com.br` (aponte um registro **A** para o IP antes) → HTTPS automático.
* Sem domínio: o script usa `IP-com-hifens.sslip.io` (ex.: `187-102-244-199.sslip.io`), que aponta para o IP e
  permite HTTPS automático (Let's Encrypt) sem comprar domínio.

## Passo a passo manual (se preferir)
```bash
ssh root@IP_DA_VPS
git clone https://github.com/SEU_USUARIO/territorial-data-pipeline.git /opt/territorial-data-pipeline
cd /opt/territorial-data-pipeline
MAPBIOMAS_URL='https://drive.google.com/uc?id=SEU_ID&export=download' bash scripts/bootstrap.sh
```

## Depois de subir
1. Abra `https://SEU_ENDERECO`, entre como `admin`.
2. O script já dispara uma sequência de demonstração: carga normal, falha simulada e execução sem mudança.
   O histórico fica pronto para quem visitar (veja `/relatorio/` e a aba *Grid* do DAG).
3. Fonte do MapBiomas: `docs/MAPBIOMAS_FONTE.md` (compartilhar como "Qualquer pessoa com o link").

## Manutenção
* Ver estado: `cd /opt/territorial-data-pipeline && docker compose ps`
* Logs: `docker compose logs -f airflow-scheduler`
* Backup: `docker compose exec postgis pg_dump -U territorial territorial > backup.sql`
* Atualizar o código: reenviar com `deploy.ps1` (o `.env` do servidor é preservado).
* Derrubar: `docker compose down` (e `-v` apaga os dados).

## Segurança — checklist
- [ ] Senhas fortes geradas e `.env` com permissão 600 (o script faz).
- [ ] Só 22, 80 e 443 abertas no firewall (o script só adiciona 80/443 se o `ufw` já estiver ativo; não ativa firewall sozinho).
- [ ] Visitantes usam o usuário *Viewer* (somente leitura); `admin` só para você.
- [ ] Apenas dados públicos no servidor.
- [ ] Considere desativar login por senha no SSH (`PasswordAuthentication no`) se só usa chave.
