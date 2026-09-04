# Topology live validation (Madalena operacional)

Este procedimento é para a Madalena **operacional**. Não exige programação.

O Cursor não tem acesso aos equipamentos. Este documento valida a feature **depois** do deploy. Resultado esperado: **PASS**, **PARTIAL** ou **FAIL**. Isso **não** é CODE PASS.

Não altere MikroTik, UniFi, Zabbix ou a VPS além de executar coleta/consulta já implantadas.

## Antes

1. Anote a versão/commit implantado (`git rev-parse --short HEAD` no servidor, ou a tag/imagem).
2. Comece com **poucos** devices (1–2 MikroTik + o controller UniFi Network). Não ligue a frota inteira na primeira passagem.
3. Confirme que os secrets de runtime existem só no ambiente:
   - MikroTik: `{PREFIX}_HOST`, `{PREFIX}_USERNAME`, `{PREFIX}_PASSWORD`
   - UniFi: `{PREFIX}_BASE_URL` (raiz da Integration API), `{PREFIX}_API_KEY`, opcional `{PREFIX}_SITE`
   - SSH: arquivo `known_hosts` montado em `/run/ssh/known_hosts` (não usar `accept-new`)
   - UniFi TLS: CA/cadeia em `NI_TLS_CA_FILE` quando possível; `{PREFIX}_VERIFY_TLS=false` é exceção de laboratório só do collector UniFi
4. Não cole logs com senha, API key, IP privado real, MAC real, serial ou hostname de cliente.

## Passos

1. **Coleta** — dispare uma coleta (scheduler `--once` ou o intervalo já configurado) só nos devices do passo anterior.
2. **MikroTik neighbors** — na API, `GET /devices/{id}/neighbors?tenant=...`. Confira identidade, interface local, MAC/chassis se o equipamento anunciou, protocolo se anunciou. Campo ausente não é erro.
3. **UniFi inventory** — os devices adotados devem aparecer no inventário do tenant (nome/modelo/MAC/estado quando a API fornecer). Uplink pode estar ausente; isso é **PARTIAL** da evidência, não falha de software por si só.
4. **Links conhecidos** — compare 2–3 ligações físicas que a equipe já conhece com `GET /devices/{id}/links` e `GET /topology`. Classifique cada uma: `confirmed` (bilateral), `unilateral`, `unresolved`, `conflicting`.
5. **Persistência** — rode uma segunda coleta. Links antigos devem permanecer (`first_seen` / `last_seen`). Ausência numa run não apaga o histórico.
6. **API** — tenant obrigatório. Sem tenant → erro. Tenant errado → vazio/404, nunca dado de outro tenant.
7. **MCP** — `get_device_neighbors`, `get_device_links`, `get_topology` com o mesmo tenant. Resposta curta (`text`) + `data`. Não deve despejar milhares de objetos (use `limit`).
8. **Secrets** — respostas e `collection_runs.error_summary` não podem conter senha, API key, community ou dump cru.

## Classificação

| Resultado | Quando usar |
|-----------|-------------|
| **PASS** | Neighbors MikroTik, inventário UniFi, alguns links conhecidos conferem, histórico permanece, API/MCP ok, sem secrets. |
| **PARTIAL** | Coleta funciona mas uplink UniFi veio vazio, ou só um lado do link aparece, ou um device falhou e os outros não. |
| **FAIL** | Dado errado persistido, tenant leak, secret em log/API, histórico apagado, ou collector write/mutation. |

Uplink UniFi documentado é só `{ "deviceId": "<uuid>" }`. Interface remota pode não existir na API. Não trate isso como FAIL se o restante estiver correto.

## Se encontrar bug de software

Abra Issue **sanitizada** em `3mstecnologia-del/madalena-network-intelligence` com:

- versão/commit
- componente (collector MikroTik, collector UniFi, ingest, API, MCP, correlation)
- expected
- observed
- erro já sanitizado
- fixture sintética mínima reproduzível quando possível

Nunca inclua: secrets, dumps completos, IPs privados reais, MACs reais, serials, topologia identificável do cliente.

Não tente corrigir no equipamento. Não peça merge. A correção entra em outro ciclo no GitHub.
