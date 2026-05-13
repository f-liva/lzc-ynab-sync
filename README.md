# lzc-ynab-sync

Docker container che sincronizza periodicamente transazioni da fonti di pagamento (Gnosis Pay, altri in arrivo) su YNAB.

## Configurazione

Copia `.env.example` in `.env` e imposta le variabili:

| Variabile | Obbligatoria | Default |
|---|---|---|
| `YNAB_SYNC_API_KEY` | sì | — |
| `YNAB_SYNC_BUDGET_ID` | sì | — |
| `YNAB_SYNC_ACCOUNT_NAME` | no | Gnosis |
| `YNAB_SYNC_GNOSIS_PK` | sì | — |
| `YNAB_SYNC_GNOSIS_ADDRESS` | sì | — |
| `YNAB_SYNC_INTERVAL` | no | 60 min |
| `YNAB_SYNC_PORT` | no | 8080 |

## Avvio

```bash
docker compose up -d
```

Apri http://localhost:8080 per vedere lo storico sync.

## Lazycat

Build `.lpk`:

```bash
cd ynab-sync-lzc && ./install.sh
```

## Connettori

- **Gnosis Pay** (SIWE auth via chiave privata Ethereum)
- PayPal, ING, Revolut — prossimamente
