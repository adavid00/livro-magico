# Livro Mágico — backend preparado para nuvem

## Execução local sem Docker

```bash
export OPENAI_API_KEY="sua-chave"
python3 servidor.py
```

Teste de saúde:

```bash
curl http://127.0.0.1:8000/health
```

## Execução local com Docker

```bash
docker build -t livro-magico-backend .
docker run --rm   -p 8000:8000   -e OPENAI_API_KEY="$OPENAI_API_KEY"   livro-magico-backend
```

Teste:

```bash
curl http://127.0.0.1:8000/health
```

## Variáveis de ambiente

- `OPENAI_API_KEY`: obrigatória.
- `PORT`: opcional; padrão `8000`.
- `HOST`: opcional; padrão `0.0.0.0`.

## Observação do MVP

Nesta versão, os arquivos de história ainda são gravados no disco do servidor.
A persistência definitiva será resolvida na próxima etapa de nuvem.
