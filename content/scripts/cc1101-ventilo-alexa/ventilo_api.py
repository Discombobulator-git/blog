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
