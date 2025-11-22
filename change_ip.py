#!/usr/bin/env python3
import json
import logging
import re
import time
import urllib.request
from pathlib import Path

# Nome del file di configurazione (stessa cartella dello script)
CONFIG_FILENAME = "change_ip_config.json"


def load_config():
    """Carica la configurazione da file JSON e applica i default."""
    config_path = Path(__file__).with_name(CONFIG_FILENAME)

    if not config_path.exists():
        raise FileNotFoundError(
            f"File di configurazione non trovato: {config_path}. "
            f"Crealo a partire da change_ip_config.json di esempio."
        )

    with config_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    # Valori di default
    defaults = {
        "check_interval": 30,
        "max_retries": 5,
        "retry_delay": 5,
        "log_level": "INFO",
    }

    cfg = {**defaults, **raw}

    # Chiavi obbligatorie
    required_keys = ["cloudflare_api_token", "zone_id", "record_name"]
    for key in required_keys:
        if not cfg.get(key):
            raise ValueError(f"Chiave obbligatoria mancante nel file di config: '{key}'")

    # Normalizza lista chat Telegram (può essere lista di int o stringhe)
    chat_ids = cfg.get("telegram_chat_ids") or []
    cfg["telegram_chat_ids"] = [int(x) for x in chat_ids]

    return cfg


def setup_logging(level_name: str):
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def is_valid_public_ipv4(ip: str) -> bool:
    """Verifica se l'IP è un IPv4 pubblico valido (molto basic)."""
    if not re.match(r"^(\d{1,3}\.){3}\d{1,3}$", ip):
        return False

    octets = ip.split(".")
    try:
        octets_int = [int(o) for o in octets]
    except ValueError:
        return False

    # Range numerici validi
    if any(o < 0 or o > 255 for o in octets_int):
        return False

    o1, o2, _, _ = octets_int

    # Escludi private e loopback principali (10.x, 127.x, 172.16-31.x, 192.168.x)
    if o1 in (10, 127):
        return False
    if o1 == 172 and 16 <= o2 <= 31:
        return False
    if o1 == 192 and o2 == 168:
        return False

    return True


def get_current_ip() -> str:
    """Ottiene l'IP pubblico corrente usando più servizi."""
    methods = [
        ("https://api.ipify.org", lambda r: r.decode("utf-8").strip()),
        ("https://ifconfig.me/ip", lambda r: r.decode("utf-8").strip()),
        ("https://checkip.amazonaws.com", lambda r: r.decode("utf-8").strip()),
    ]

    last_error = None

    for url, parser in methods:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                ip = parser(response.read())
                if is_valid_public_ipv4(ip):
                    logging.debug(f"IP ottenuto da {url}: {ip}")
                    return ip
                else:
                    logging.warning(f"Risposta da {url} non è un IP pubblico valido: '{ip}'")
        except Exception as e:
            logging.warning(f"Errore nel recupero dell'IP da {url}: {e}")
            last_error = e

    raise RuntimeError(f"Impossibile ottenere un indirizzo IP pubblico valido: {last_error}")


def cloudflare_request(cfg, method: str, url: str, data: dict | None = None) -> dict:
    """Effettua una richiesta all'API Cloudflare (TLS verificato)."""
    headers = {
        "Authorization": f"Bearer {cfg['cloudflare_api_token']}",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(url, headers=headers, method=method)
    if data is not None:
        req.data = json.dumps(data).encode("utf-8")

    with urllib.request.urlopen(req, timeout=15) as response:
        body = response.read().decode("utf-8")
        return json.loads(body)


def get_cloudflare_record(cfg):
    """Recupera ID, IP e stato proxy del record A su Cloudflare."""
    url = (
        f"https://api.cloudflare.com/client/v4/zones/"
        f"{cfg['zone_id']}/dns_records?name={cfg['record_name']}&type=A"
    )
    data = cloudflare_request(cfg, "GET", url)

    if data.get("success") and data.get("result"):
        rec = data["result"][0]
        return rec["id"], rec["content"], rec["proxied"]

    raise RuntimeError("Record DNS A non trovato su Cloudflare")


def update_cloudflare_dns(cfg, record_id: str, ip: str, proxied: bool) -> bool:
    """Aggiorna il record A con il nuovo IP e impostazione proxy."""
    url = (
        f"https://api.cloudflare.com/client/v4/zones/"
        f"{cfg['zone_id']}/dns_records/{record_id}"
    )
    payload = {
        "type": "A",
        "name": cfg["record_name"],
        "content": ip,
        "ttl": 1,       # 'automatic' in Cloudflare
        "proxied": proxied,
    }
    resp = cloudflare_request(cfg, "PUT", url, payload)
    return bool(resp.get("success"))


def send_telegram_message(cfg, message: str):
    """Invia un messaggio Telegram a tutte le chat configurate (se configurato)."""
    bot_token = cfg.get("telegram_bot_token")
    chat_ids = cfg.get("telegram_chat_ids") or []

    if not bot_token or not chat_ids:
        # Telegram opzionale: se non configurato, non fa nulla.
        logging.debug("Telegram non configurato, salto invio messaggio.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    for chat_id in chat_ids:
        payload = {
            "chat_id": chat_id,
            "text": message,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.getcode() == 200:
                    logging.info(f"Messaggio Telegram inviato a chat {chat_id}")
                else:
                    content = response.read().decode("utf-8")
                    logging.error(
                        f"Invio messaggio Telegram fallito per chat {chat_id}: "
                        f"{response.getcode()} {content}"
                    )
        except Exception as e:
            logging.error(f"Errore nell'invio del messaggio Telegram a {chat_id}: {e}")


def main():
    cfg = load_config()
    setup_logging(cfg["log_level"])

    logging.info(f"Avvio change_ip.py per {cfg['record_name']}")
    logging.info(f"Intervallo controllo: {cfg['check_interval']} secondi")

    last_ip = None

    while True:
        try:
            current_ip = get_current_ip()

            if current_ip != last_ip:
                logging.info(f"IP rilevato: {current_ip} (precedente: {last_ip})")

                # tenta update Cloudflare con retry
                for attempt in range(1, cfg["max_retries"] + 1):
                    try:
                        record_id, cf_ip, cf_proxied = get_cloudflare_record(cfg)
                        logging.info(
                            f"Record Cloudflare attuale: {cf_ip}, proxied={cf_proxied}"
                        )

                        if current_ip != cf_ip or cf_proxied:
                            logging.info(
                                f"Aggiorno DNS: {cfg['record_name']} → {current_ip}, "
                                f"proxied=False"
                            )
                            success = update_cloudflare_dns(
                                cfg, record_id, current_ip, proxied=False
                            )
                            if success:
                                logging.info("DNS aggiornato correttamente.")
                                msg = (
                                    f"IP pubblico aggiornato per {cfg['record_name']}:\n"
                                    f"{current_ip}"
                                )
                                send_telegram_message(cfg, msg)
                                last_ip = current_ip
                                break
                            else:
                                logging.error("Aggiornamento DNS fallito (success=False)")
                        else:
                            logging.info("Cloudflare già allineato, nessun update necessario.")
                            last_ip = current_ip
                            break

                    except Exception as e:
                        logging.error(
                            f"Tentativo {attempt}/{cfg['max_retries']} fallito: {e}"
                        )
                        if attempt < cfg["max_retries"]:
                            logging.info(
                                f"Riprovo tra {cfg['retry_delay']} secondi..."
                            )
                            time.sleep(cfg["retry_delay"])
                        else:
                            logging.error(
                                "Numero massimo di tentativi raggiunto, rinuncio fino al prossimo ciclo."
                            )

            else:
                logging.debug("IP invariato, nessuna azione.")

        except Exception as e:
            logging.error(f"Errore nel ciclo principale: {e}")

        time.sleep(cfg["check_interval"])


if __name__ == "__main__":
    main()
