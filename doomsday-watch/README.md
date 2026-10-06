# Doomsday ticket watch

Checks **Avengers: Doomsday** bookings in **Delhi/NCR** on [BookMyShow](https://in.bookmyshow.com/movies/national-capital-region-ncr/avengers-doomsday/ET00439706) and [District](https://www.district.in/movies/avengers-doomsday-movie-tickets-in-delhi-ncr-MV176735) every **10 minutes**. The first confirmed booking on either site sends an alert through every configured channel. It runs as a persistent service on a cloud VM, so your PC can be off.

The first check can alert immediately if sales have already started. State survives restarts, and each successful channel is sent only once per site. Failed delivery is retried. After three consecutive unreadable checks, a fault alert says that the site could not be checked. The script does not select seats or purchase tickets.

## Why these signals

- **BookMyShow:** Uses a Safari TLS profile and checks the `showDateCode` of real shows. BookMyShow can return a page for a different date than the URL requests; a page load or “Book” text is insufficient.
- **District:** Uses its server-rendered `__NEXT_DATA__`. The upcoming page has empty `showDates` and `cinemas`; when the layout switches to live bookings, actual sessions appear in `movieSessions[].arrangedSessions[].sessions`.

The [SeatSniper source](https://github.com/Ishannaik/seatsniper) established the BookMyShow date rule. The [venue watcher reference](https://github.com/venomousreptile1-maker/bms-sbndwatch/blob/main/bms_venue_watch.py) targets movies already on sale; this watcher handles the first opening.

## Configure alerts

Copy `.env.example` to `.env`. Set any combination of these:

| Channel | Required settings | Notes |
| --- | --- | --- |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Create a bot with BotFather, message it once, then get your chat ID from Telegram's bot updates. |
| Discord DM | `DISCORD_BOT_TOKEN`, `DISCORD_USER_ID` | Your bot must be allowed to DM your user account. |
| Email via Resend | `RESEND_API_KEY`, `EMAIL_TO` | Recommended on DigitalOcean. Uses HTTPS; its test sender can email the Resend account address. |
| Email via SMTP | `SMTP_HOST`, `EMAIL_FROM`, `EMAIL_TO`; usually `SMTP_USER`, `SMTP_PASSWORD` | For hosts that permit SMTP. DigitalOcean blocks outbound 25, 465, and 587. |
| ntfy phone push | `NTFY_TOPIC` | Install ntfy on your phone and subscribe to a long random topic. A public ntfy.sh topic can be read by anyone who knows its name. |

Use **at least two** channels for a critical alert. Keep `.env` private and out of Git. After setup, run the test alert and verify every phone/app/email inbox received it.

For Telegram, create a bot with [@BotFather](https://t.me/BotFather) using `/newbot`, open the new bot, and send `/start`. On the VM, run `sudo -u ubuntu /home/ubuntu/doomsday-watch/.venv/bin/python /home/ubuntu/doomsday-watch/setup_telegram.py`. Paste the token at its hidden prompt. It finds your chat ID, sends a test, and updates `.env`. After you receive the test, run `systemctl restart doomsday-watch`; the saved polling time prevents an early repeat check.

To alert a friend, have them open the bot and press **Start** after the Telegram listener is installed below. They will receive a welcome reply and be added automatically. Telegram delivery is recorded separately for each recipient, so a failed send to one person can be retried without repeating successful deliveries to others. Do not share the bot token.

For automatic subscriptions and welcome replies, install `doomsday-telegram.service` alongside the watcher: `cp doomsday-telegram.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now doomsday-telegram`. A private `/start` sends a welcome immediately and stores that chat ID in `telegram_subscribers.json`; future alerts include it automatically. `/stop` removes an added subscriber. The account configured as `TELEGRAM_CHAT_ID` remains the owner alert chat. The bot listener uses Telegram long polling and exposes no inbound port.

For email on DigitalOcean, create a free [Resend](https://resend.com/pricing/) account using the inbox where you want alerts. Create an API key with **Sending access**. Run `sudo -u ubuntu /home/ubuntu/doomsday-watch/.venv/bin/python /home/ubuntu/doomsday-watch/setup_email.py` on the VM and enter that same email address and the key at its hidden prompt. The test sender `onboarding@resend.dev` can email your Resend account address without a custom domain. After the test reaches your inbox, run `systemctl restart doomsday-watch`. [DigitalOcean blocks SMTP](https://docs.digitalocean.com/support/why-is-smtp-blocked/), so an ordinary Gmail SMTP app password will not work from this Droplet.

## Local check

Requires Python 3.10+.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your own alert credentials.
python watch.py --test-alert
python watch.py --once
```

`--once` checks both sites and exits. By default, `python watch.py` continues checking once every 10 minutes. `POLL_SECONDS` cannot be set below 600.

## Run without your PC: $6/month Bangalore VM

Choose a [DigitalOcean Basic Regular Droplet](https://www.digitalocean.com/pricing/droplets) with **1 GiB RAM, 1 vCPU, 25 GiB SSD ($6/month)** in its [Bangalore region](https://www.digitalocean.com/products/droplets). Select Ubuntu 24.04 and SSH-key authentication. Leave paid backups and other add-ons off to keep the server price below $10/month; taxes may be extra. This small Python process does not require Docker on a 1 GiB VM. No inbound port is needed beyond SSH.

1. Create the Droplet and save its IP and your SSH private key. Ubuntu images normally use the `root` login; the commands below create an unprivileged `ubuntu` account for the watcher. If your image already has `ubuntu`, skip creating it.
2. Connect as root, install Python, and create the watcher account:

```bash
apt update && apt install -y python3 python3-venv python3-pip
id ubuntu >/dev/null 2>&1 || useradd -m -s /bin/bash ubuntu
```

3. Transfer the source files to `/home/ubuntu/doomsday-watch` and assign ownership to `ubuntu`. Create `.env` from `.env.example`, fill in your alert channels, and protect it:

```bash
chown -R ubuntu:ubuntu /home/ubuntu/doomsday-watch
sudo -u ubuntu python3 -m venv /home/ubuntu/doomsday-watch/.venv
sudo -u ubuntu /home/ubuntu/doomsday-watch/.venv/bin/pip install -r /home/ubuntu/doomsday-watch/requirements.txt
sudo -u ubuntu cp /home/ubuntu/doomsday-watch/.env.example /home/ubuntu/doomsday-watch/.env
chmod 600 /home/ubuntu/doomsday-watch/.env
# Edit /home/ubuntu/doomsday-watch/.env with your own credentials.
```

4. Send a test alert, then install and start the service:

```bash
cd /home/ubuntu/doomsday-watch
sudo -u ubuntu .venv/bin/python watch.py --test-alert
cp doomsday-watch.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now doomsday-watch
systemctl status doomsday-watch
journalctl -u doomsday-watch -f
```

`systemd` starts the monitor after reboots and restarts it after crashes. `state.json` remains in the watcher directory, so delivered alerts are not repeated after restarts. The process exposes no web port.

For an independent outage warning, create a [Healthchecks.io](https://healthchecks.io/pricing/) check with a **10-minute period and at least 5-minute grace time**, connect its email or Telegram alert, and set `HEALTHCHECK_URL` to its private ping URL. The script pings after each cycle, including cycles with site errors. If the VM or process stops, Healthchecks.io detects the missing ping; site read failures still produce the monitor's own alerts.

To stop checking after booking, run `systemctl disable --now doomsday-watch`. Delete the Droplet to stop its recurring charge.

## Limits

Ten-minute polling means the alert usually arrives within 10 minutes **if both sites remain reachable and a channel delivers**. Neither site guarantees that an opened show remains available long enough to book. BookMyShow and District can change their page formats or block automated requests; faults are reported rather than treated as “no tickets.” The script observes booking availability and gives you a direct link to book manually.

## Tests

```bash
python -m unittest -v test_watch.py test_telegram_bot.py
```
