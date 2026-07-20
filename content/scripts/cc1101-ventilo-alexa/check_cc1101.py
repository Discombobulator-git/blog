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
