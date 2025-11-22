# change_ip - Cloudflare Dynamic DNS + Notifica Telegram

Questo script aggiorna automaticamente un record **A** su Cloudflare con il tuo **IP pubblico corrente**.  
Facoltativamente può inviare una **notifica Telegram** ogni volta che l'IP cambia.

Pensato per girare in modo continuativo su un device sempre acceso (es. mini-PC, SBC, server casalingo).

---

## Funzionalità

- Rileva periodicamente l’IP pubblico chiamando più servizi esterni.
- Legge da Cloudflare il record A configurato.
- Se:
  - l’IP è cambiato **oppure**
  - il record su Cloudflare è ancora in modalità proxy (`proxied = true`)
  
  allora:
  - aggiorna il record A con il nuovo IP;
  - imposta `proxied = false` (disabilita il proxy Cloudflare, modalità DNS only);
  - invia un messaggio Telegram (se configurato).

---

## File del progetto

- `change_ip.py`  
  Script principale da eseguire (o da usare con systemd).

- `change_ip_config.json`  
  File di configurazione **locale** (contiene token e parametri).  
  **Non** deve essere committato su repository pubblici.

---

## Requisiti

- Sistema operativo: Linux (testato), ma va bene anche altri sistemi con Python 3.
- **Python 3.8+**
- Connettività Internet verso:
  - Cloudflare API
  - Servizi di IP pubblico (`api.ipify.org`, `ifconfig.me`, `checkip.amazonaws.com`)
  - API Telegram (se usi la parte Telegram)

Lo script usa **solo la libreria standard di Python**, quindi non servono `pip install`.

---

## Installazione

1. Copia i file in una cartella, ad esempio:

   ```bash
   /home/radxa/change_ip/
