# Scripts operacionais

Os scripts deste diretório fazem parte do conhecimento reproduzível do projeto. Utilitários `ni_*` validam paridade API/MCP, ausência de reflexão de secrets e classificação de evidência física usando o estado já persistido.

## Limites de segurança

- Não executar contra ambiente de cliente sem autorização operacional.
- As saídas podem conter nomes, IDs e topologia; preserve-as somente como evidência privada.
- Secrets são lidos apenas do runtime e nunca devem ser impressos ou gravados no repositório.
- Esses validadores não substituem a comparação humana com a topologia física conhecida.
