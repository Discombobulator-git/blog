---
title: "CC1101: driving a ceiling fan (Raspberry Pi Zero W)"
date: 2026-07-20T10:00:00+02:00
tags: ["RF", "SDR", "CC1101", "Raspberry Pi", "home automation"]
summary: "Production scripts to reproduce a ceiling fan remote with a CC1101 and a Raspberry Pi Zero W."
---

Full context in the article [Making a ceiling fan talk]({{< ref "/posts/cc1101-ventilo-alexa/index.en.md" >}}). These scripts are the version running in production today, ported to a Raspberry Pi Zero W (pigpio, wave DMA).

Wiring (standard 40-pin header):

| Signal | GPIO | Pin |
|---|---|---|
| CS   | GPIO8  (CE0) | 24 |
| CLK  | GPIO11 | 23 |
| MOSI | GPIO10 | 19 |
| MISO | GPIO9  | 21 |
| GDO0 | GPIO24 | 18 |

System requirements:

```bash
sudo apt install pigpio python3-pigpio
sudo systemctl enable --now pigpiod
pip install spidev pigpio flask
```

## `check_cc1101.py` — SPI wiring check

Reads the CC1101's `PARTNUM` and `VERSION` registers. On a genuine chip, `VERSION` is usually `0x14` (sometimes `0x04` or `0x03` depending on the manufacturing batch). If you get `0x00` or `0xFF`, that's a wiring problem (MISO/MOSI swapped, CS not connected, missing power or ground), not a real response from the chip.

[Download check_cc1101.py](check_cc1101.py)

```python
#!/usr/bin/env python3
"""
Verification rapide de la communication SPI avec le CC1101.
Lit les registres PARTNUM (0x30) et VERSION (0x31).
Sur un CC1101 authentique, VERSION vaut generalement 0x14 (parfois 0x04
ou 0x03 selon le lot de fabrication), PARTNUM vaut 0x00.
"""

import spidev
import time

SPI_BUS = 0
SPI_DEVICE = 0  # CE0 = GPIO8

# Adresses des registres de statut. Le bit de lecture (0x80) et le bit
# burst (0x40) doivent tous les deux etre positionnes pour lire un
# registre de statut sur le CC1101 (sinon on lit un registre de config).
READ_BURST = 0xC0

REG_PARTNUM = 0x30
REG_VERSION = 0x31
STROBE_SRES = 0x30  # reset du chip (attention: correspond aussi a PARTNUM
                     # en lecture, mais en ecriture c'est un strobe)


def open_spi():
    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEVICE)
    spi.max_speed_hz = 500000
    spi.mode = 0
    return spi


def read_status_register(spi, addr):
    resp = spi.xfer2([READ_BURST | addr, 0x00])
    return resp[1]


def reset_chip(spi):
    spi.xfer2([0x30])  # strobe SRES
    time.sleep(0.01)


def main():
    spi = open_spi()
    try:
        reset_chip(spi)
        partnum = read_status_register(spi, REG_PARTNUM)
        version = read_status_register(spi, REG_VERSION)

        print(f"PARTNUM  = 0x{partnum:02X}")
        print(f"VERSION  = 0x{version:02X}")

        if version in (0x00, 0xFF):
            print()
            print("ATTENTION: VERSION = 0x00 ou 0xFF, ca sent le probleme")
            print("de cablage (MISO/MOSI inverses, CS non connecte,")
            print("alimentation absente ou GND manquant), pas une vraie")
            print("reponse du CC1101.")
        else:
            print()
            print("OK: le CC1101 repond, le SPI fonctionne.")
    finally:
        spi.close()


if __name__ == "__main__":
    main()
```

## `cc1101_tx_ventilo_pigpio.py` — OOK transmission via pigpio

Configures the CC1101 then transmits the code matching a button. Each real frame is 33 bits (see the article for the story of that hidden bit), generated via pigpio wave DMA for microsecond-accurate timing. Usage:

```bash
python3 cc1101_tx_ventilo_pigpio.py <button>
# available buttons: lumiere, onoff, v1, v2, v3, v4, v5, v6, inversion
```

[Download cc1101_tx_ventilo_pigpio.py](cc1101_tx_ventilo_pigpio.py)

```python
#!/usr/bin/env python3
"""
Transmission OOK asynchrone via CC1101, timing precis via pigpio (wave DMA).

Portage du script original ecrit pour Pi 5 (bit-banging manuel via lgpio,
necessaire car pigpio ne fonctionne pas sur la puce RP1). Sur un Pi Zero W
(BCM2835 classique, sans RP1), pigpio fonctionne nativement et genere les
impulsions par DMA : timing garanti au microseconde pres, sans boucle
d'attente active bloquante.

Cablage (identique Pi 5 / Pi Zero W, header 40 broches standard) :
    CS   -> GPIO8  (CE0, pin 24)
    CLK  -> GPIO11 (pin 23)
    MOSI -> GPIO10 (pin 19)
    MISO -> GPIO9  (pin 21)
    GDO0 -> GPIO24 (pin 18)

Prerequis :
    sudo apt install pigpio python3-pigpio
    sudo systemctl enable --now pigpiod
    pip install spidev pigpio   (dans le venv)

Usage :
    python3 cc1101_tx_ventilo_pigpio.py <bouton>
"""

import spidev
import time
import sys
import pigpio

SPI_BUS = 0
SPI_DEVICE = 0
SPI_SPEED_HZ = 500000
GDO0_PIN = 24  # meme broche que sur le Pi 5 (GPIO25 y etait endommagee)

WRITE_BURST = 0x40
READ_BURST = 0xC0

REG = {
    'IOCFG2':   0x00, 'IOCFG0':   0x02, 'FIFOTHR':  0x03,
    'PKTCTRL1': 0x07, 'PKTCTRL0': 0x08, 'FSCTRL1':  0x0B,
    'FREQ2':    0x0D, 'FREQ1':    0x0E, 'FREQ0':    0x0F,
    'MDMCFG4':  0x10, 'MDMCFG3':  0x11, 'MDMCFG2':  0x12,
    'DEVIATN':  0x15, 'MCSM0':    0x18, 'FREND0':   0x22,
    'FSCAL3':   0x23, 'FSCAL2':   0x24, 'FSCAL1':   0x25, 'FSCAL0': 0x26,
    'TEST2':    0x2C, 'TEST1':    0x2D, 'TEST0':    0x2E,
}
PATABLE_ADDR = 0x3E

SRES, SCAL, STX, SIDLE = 0x30, 0x33, 0x35, 0x36

CONFIG = {
    'IOCFG2': 0x2E, 'IOCFG0': 0x2D, 'FIFOTHR': 0x47,
    'PKTCTRL1': 0x04, 'PKTCTRL0': 0x32, 'FSCTRL1': 0x06,
    'FREQ2': 0x10, 'FREQ1': 0xB0, 'FREQ0': 0x71,
    'MDMCFG4': 0xF8, 'MDMCFG3': 0x83, 'MDMCFG2': 0x30,
    'DEVIATN': 0x15, 'MCSM0': 0x18, 'FREND0': 0x11,
    'FSCAL3': 0xE9, 'FSCAL2': 0x2A, 'FSCAL1': 0x00, 'FSCAL0': 0x1F,
    'TEST2': 0x81, 'TEST1': 0x35, 'TEST0': 0x09,
}
PATABLE = [0x00, 0xC6]

CODES = {
    'lumiere':   '01010110110011110110100101000001',
    'onoff':     '01010110110011110110010101011100',
    'v1':        '01010110110011110110001000011111',
    'v2':        '01010110110011110110100001100010',
    'v3':        '01010110110011110110011001001110',
    'v4':        '01010110110011110110001101101001',
    'v5':        '01010110110011110110010010000000',
    'v6':        '01010110110011110110101010011111',
    'inversion': '01010110110011110110100011001000',
}

SHORT_US = 300
LONG_US = 700
INTERFRAME_GAP_US = 7440
REPEATS = 10


def open_spi():
    spi = spidev.SpiDev()
    spi.open(SPI_BUS, SPI_DEVICE)
    spi.max_speed_hz = SPI_SPEED_HZ
    spi.mode = 0b00
    return spi


def write_reg(spi, addr, value):
    spi.xfer2([addr, value])


def write_burst(spi, addr, values):
    spi.xfer2([addr | WRITE_BURST] + list(values))


def strobe(spi, cmd):
    spi.xfer2([cmd])


def read_marcstate(spi):
    resp = spi.xfer2([0x35 | READ_BURST, 0x00])
    return resp[1] & 0x1F


def configure_cc1101(spi):
    print("[*] Reset...")
    strobe(spi, SRES)
    time.sleep(0.01)
    print("[*] Ecriture des registres...")
    for name, addr in REG.items():
        write_reg(spi, addr, CONFIG[name])
    write_burst(spi, PATABLE_ADDR, PATABLE)
    time.sleep(0.01)
    print("[*] Calibration du synthetiseur (SCAL)...")
    strobe(spi, SCAL)
    time.sleep(0.01)
    print("[*] Configuration terminee.")


def build_wave(pi, bits_with_toggle):
    """Construit la liste de pulses pigpio pour une seule trame (33 bits).

    Meme convention que la version bit-banging :
    bit '1' -> HIGH pendant LONG_US, puis LOW pendant SHORT_US
    bit '0' -> HIGH pendant SHORT_US, puis LOW pendant LONG_US
    """
    pulses = []
    for bit in bits_with_toggle:
        if bit == '1':
            pulses.append(pigpio.pulse(1 << GDO0_PIN, 0, LONG_US))
            pulses.append(pigpio.pulse(0, 1 << GDO0_PIN, SHORT_US))
        else:
            pulses.append(pigpio.pulse(1 << GDO0_PIN, 0, SHORT_US))
            pulses.append(pigpio.pulse(0, 1 << GDO0_PIN, LONG_US))
    return pulses


def wave_tx(pi, bits, repeats):
    """Genere le signal OOK sur GDO0 via wave DMA pigpio.

    Chaque trame reelle fait 33 bits, pas 32 (voir le script d'origine pour
    le detail de cette decouverte) : un bit de fin qui alterne 0/1/0/1 a
    chaque repetition est ajoute apres les 32 bits du code.
    """
    pi.wave_clear()
    toggle_bit = '0'

    for r in range(repeats):
        frame = bits + toggle_bit
        pulses = build_wave(pi, frame)

        pi.wave_add_generic(pulses)
        wave_id = pi.wave_create()

        pi.wave_send_once(wave_id)
        while pi.wave_tx_busy():
            time.sleep(0.001)

        pi.wave_delete(wave_id)

        pi.write(GDO0_PIN, 0)
        time.sleep(INTERFRAME_GAP_US / 1e6)
        toggle_bit = '1' if toggle_bit == '0' else '0'


def transmit(spi, pi, code_name):
    bits = CODES[code_name]
    print(f"[*] Transmission de '{code_name}' : {bits} ({REPEATS}x repetitions, via pigpio wave)")

    strobe(spi, STX)
    time.sleep(0.005)

    state = read_marcstate(spi)
    print(f"[*] MARCSTATE apres STX : {hex(state)} "
          f"({'TX confirme' if state == 0x13 else 'PAS en TX'})")

    wave_tx(pi, bits, REPEATS)

    strobe(spi, SIDLE)
    print("[*] Transmission terminee, chip repasse en IDLE.")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CODES:
        print(f"Usage: python3 {sys.argv[0]} <bouton>")
        print(f"Boutons disponibles : {', '.join(CODES.keys())}")
        sys.exit(1)

    code_name = sys.argv[1]

    pi = pigpio.pi()
    if not pi.connected:
        print("Erreur: impossible de se connecter a pigpiod.")
        print("Verifie que le daemon tourne: sudo systemctl status pigpiod")
        sys.exit(1)

    pi.set_mode(GDO0_PIN, pigpio.OUTPUT)
    pi.write(GDO0_PIN, 0)

    spi = open_spi()

    try:
        configure_cc1101(spi)
        transmit(spi, pi, code_name)
    finally:
        pi.write(GDO0_PIN, 0)
        pi.wave_clear()
        pi.stop()
        spi.close()


if __name__ == "__main__":
    main()
```

## `ventilo_api.py` — HTTP bridge (Flask)

Exposes each button as an HTTP route (`GET /<button>`), meant to be called from Home Assistant (`rest_command`) or any other home automation system. Runs the transmit script as a subprocess inside the dedicated venv.

```bash
python3 ventilo_api.py
# service available on http://<pi-ip>:8765/
```

[Download ventilo_api.py](ventilo_api.py)

```python
#!/usr/bin/env python3

import subprocess
from pathlib import Path

from flask import Flask, jsonify

app = Flask(__name__)

SCRIPT = Path("/home/pi/Cc1101_tx_ventilo_pigpio.py")
PYTHON = Path("/home/pi/ventilo-env/bin/python3")

COMMANDES = {
    "lumiere",
    "onoff",
    "v1",
    "v2",
    "v3",
    "v4",
    "v5",
    "v6",
    "inversion",
}


@app.get("/<commande>")
def envoyer_commande(commande: str):
    if commande not in COMMANDES:
        return jsonify(
            success=False,
            error=f"Commande inconnue : {commande}",
            commandes=sorted(COMMANDES),
        ), 404

    try:
        resultat = subprocess.run(
            [str(PYTHON), str(SCRIPT), commande],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )

        return jsonify(
            success=True,
            commande=commande,
            stdout=resultat.stdout.strip(),
        )

    except subprocess.CalledProcessError as erreur:
        return jsonify(
            success=False,
            commande=commande,
            stdout=erreur.stdout.strip(),
            stderr=erreur.stderr.strip(),
            returncode=erreur.returncode,
        ), 500

    except subprocess.TimeoutExpired:
        return jsonify(
            success=False,
            commande=commande,
            error="Expiration du délai d’exécution",
        ), 504


@app.get("/")
def accueil():
    return jsonify(
        service="API ventilateur CC1101",
        commandes=sorted(COMMANDES),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765)
```
